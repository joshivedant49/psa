from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse,HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.db.models import (
    Count, Sum, Q, F, DecimalField, ExpressionWrapper
)
from django.utils import timezone

from .models import (
    Sport, Batch, ExpertiseLevel, Duration, FeeStructures,
    StudentData, ActivityLog,SystemUser,CoachPermission, Coach,
    CoachAttendance, StudentAttendance, Payment, ActivityLog,SiteVisit
)
from functools import wraps
from django.views.decorators.csrf import csrf_exempt
from .report_views import reports_page, report_pdf, report_count

from .validators import (
    collect, validate_login, validate_user_create, validate_coach,
    validate_student_personal, validate_student_parent, validate_student_sport,
    validate_sport, validate_batch, validate_expertise_level,
    validate_fee_structure, validate_password_reset,
)
from calendar import monthrange
import json as _json
import csv
from django.contrib.auth.decorators import login_required
from django.db import transaction
from collections import defaultdict
from dateutil.relativedelta import relativedelta
# ════════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ════════════════════════════════════════════════════════════════════

def get_current_user(request):
    uid = request.session.get('user_id')
    if uid:
        try:
            return SystemUser.objects.get(pk=uid, is_active=True)
        except SystemUser.DoesNotExist:
            pass
    return None


def login_required(view_fn):
    @wraps(view_fn)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return redirect('login')
        request.current_user = user
        return view_fn(request, *args, **kwargs)
    return wrapper


def admin_required(view_fn):
    @wraps(view_fn)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return redirect('login')
        if not user.is_admin:
            messages.error(request, 'Admin access required.')
            return redirect('home')
        request.current_user = user
        return view_fn(request, *args, **kwargs)
    return wrapper



def permission_required(module):
    """Admin always allowed. Coach/User needs explicit module permission."""

    def decorator(view_fn):

        @wraps(view_fn)
        def wrapper(request, *args, **kwargs):

            user = get_current_user(request)

            if not user:
                return redirect('login')

            # Admin bypass
            if user.is_admin:
                request.current_user = user
                return view_fn(request, *args, **kwargs)

            # Permission check
            has_perm = CoachPermission.objects.filter(
                user=user,
                module=module,
                allowed=True
            ).exists()

            if not has_perm:
                messages.error(request, 'You do not have access to this module.')
                return redirect('home')

            request.current_user = user
            return view_fn(request, *args, **kwargs)

        return wrapper

    return decorator

def _log(activity_type, title, description='', student=None):
    ActivityLog.objects.create(
        activity_type=activity_type, title=title,
        description=description, student=student,
    )


def _expiry_buckets():
    today    = date.today()
    week_end = today + timedelta(days=7)
    month_end= today + timedelta(days=30)
    qs = StudentData.objects.select_related('sport','batch','expertise_level','duration')
    return (
        qs.filter(subscription_expiry=today),
        qs.filter(subscription_expiry__gt=today, subscription_expiry__lte=week_end,  status='active'),
        qs.filter(subscription_expiry__gt=week_end, subscription_expiry__lte=month_end, status='active'),
    )

def _int_or_none(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None

# ════════════════════════════════════════════════════════════════════
#  LOGIN / LOGOUT
# ════════════════════════════════════════════════════════════════════

def login_view(request):
    # ── Count every page load ──
    SiteVisit.objects.create()
    visitor_count = SiteVisit.objects.count()

    if request.method == 'POST':
        data = request.POST
        errs = validate_login(data)
        if errs:
            for msg in collect(errs): messages.error(request, msg)
        else:
            username = data.get('username', '').strip()
            password = data.get('password', '')
            try:
                user = SystemUser.objects.get(username=username, is_active=True)
                if user.check_password(password):
                    request.session['user_id'] = user.pk
                    request.session.set_expiry(86400 * 7)
                    user.last_login = timezone.now()
                    user.save(update_fields=['last_login'])
                    _log('login', f'{user.full_name} logged in', f'Role: {user.role}')
                    return redirect('home')
                else:
                    messages.error(request, 'Invalid username or password.')
            except SystemUser.DoesNotExist:
                messages.error(request, 'Invalid username or password.')

    return render(request, 'auth/pradip_sports_academy.html', {
        'visitor_count': visitor_count,
    })

def logout_view(request):
    user = get_current_user(request)
    if user:
        _log('logout', f'{user.full_name} logged out')
    request.session.flush()
    return redirect('login')


# ════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ════════════════════════════════════════════════════════════════════

@login_required
def home(request):
    user  = request.current_user
    today = date.today()
    week_end  = today + timedelta(days=7)
    month_end = today + timedelta(days=30)

    # ── Auto-sync expired status ──────────────────────────────
    StudentData.objects.filter(
        status='active',
        subscription_expiry__lt=today
    ).update(status='expired')
    # ─────────────────────────────────────────────────────────

    # Base querysets
    all_students_qs   = StudentData.objects.all()
    active_student_qs = all_students_qs.filter(status='active')

    if user.is_coach and user.coach:
        all_students_qs   = all_students_qs.filter(assigned_coach=user.coach)
        active_student_qs = active_student_qs.filter(assigned_coach=user.coach)

    # ── Summary counts ────────────────────────────────────────
    total_students = all_students_qs.count()
    active_subs    = active_student_qs.count()
    expired_count  = all_students_qs.filter(status='expired').count()

    total_sports  = Sport.objects.filter(is_active=True).count()
    total_batches = Batch.objects.filter(is_active=True).count()
    coach_count   = Coach.objects.filter(status='active').count()

    # ── Expiry counts ─────────────────────────────────────────
    expiring_today_count = all_students_qs.filter(
        subscription_expiry=today
    ).count()

    expiring_week = all_students_qs.filter(
        subscription_expiry__gte=today,
        subscription_expiry__lte=week_end
    ).count()

    # ── Financial ─────────────────────────────────────────────
    # Pending dues — ALL students regardless of status
    pending_dues = StudentData.objects.filter(
        fee_due__gt=0
    ).aggregate(t=Sum('fee_due'))['t']

    pending_payments_count = StudentData.objects.filter(
        fee_due__gt=0
    ).count()

    # Month revenue — actual payments received this month
    month_revenue = Payment.objects.filter(
        payment_date__year=today.year,
        payment_date__month=today.month,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # ── Renewal rate — dynamic ────────────────────────────────
    # Formula: active / (active + expired) * 100
    # Represents what % of students are still active vs lapsed
    renewed_count = all_students_qs.filter(is_renewal=True).count()
    ever_expired  = expired_count + renewed_count

    renewal_rate = (
        round(renewed_count / ever_expired * 100)
        if ever_expired > 0 else 0
    )

    # ── Alert students ────────────────────────────────────────
    due_today_qs, due_week_qs, _ = _expiry_buckets()
    if user.is_coach and user.coach:
        due_today_qs = due_today_qs.filter(assigned_coach=user.coach)
        due_week_qs  = due_week_qs.filter(assigned_coach=user.coach)
    alert_students = list(due_today_qs[:3]) + list(due_week_qs[:2])

    # ── Sport distribution ────────────────────────────────────
    sport_counts = (
        active_student_qs
        .values('sport__name', 'sport__icon')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    max_c = sport_counts[0]['count'] if sport_counts else 1
    sport_data = [
        {
            'name':    s['sport__name'],
            'icon':    s['sport__icon'],
            'count':   s['count'],
            'pct':     round(s['count'] / total_students * 100) if total_students else 0,
            'bar_pct': round(s['count'] / max_c * 100) if max_c else 0,
        }
        for s in sport_counts
    ]

    # ── Recent activity & upcoming renewals ───────────────────
    recent_activity = ActivityLog.objects.select_related('student')[:8]

    upcoming_renewals = all_students_qs.filter(
        subscription_expiry__gte=today,
        subscription_expiry__lte=week_end,
    ).select_related('sport', 'batch').order_by('subscription_expiry')[:6]

    # ── Notification badge count ──────────────────────────────
    notif_count = all_students_qs.filter(
        subscription_expiry__gte=today,
        subscription_expiry__lte=week_end,
    ).count()

    return render(request, 'home/home.html', {
        'user':                   user,
        # 'total_students':         total_students,
        'active_subs':            active_subs,
        'expired_count':          expired_count,
        'total_sports':           total_sports,
        'total_batches':          total_batches,
        'month_revenue':          month_revenue,
        'renewal_rate':           renewal_rate,       
        'expiring_today_count':   expiring_today_count,
        'expiring_week':          expiring_week,
        'pending_payments_count': pending_payments_count,
        'pending_dues':           pending_dues,
        'alert_students':         alert_students,
        'sport_data':             sport_data,
        'recent_activity':        recent_activity,
        'upcoming_renewals':      upcoming_renewals,
        # 'notif_count':            notif_count,
        # 'coach_count':            coach_count,
        'today':                  today,
    })

# ════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ════════════════════════════════════════════════════════════════════

@login_required
@permission_required('notifications')
def notifications(request):
    due_today, due_week, due_month = _expiry_buckets()
    return render(request, 'notifications/notifications.html', {
        'user': request.current_user,
        'due_today': due_today, 'due_week': due_week, 'due_month': due_month,
        'count_today': due_today.count(), 'count_week': due_week.count(), 'count_month': due_month.count(),
    })


# ════════════════════════════════════════════════════════════════════
#  USER MANAGEMENT (admin only)
# ════════════════════════════════════════════════════════════════════

@admin_required
def user_list(request):
    users = SystemUser.objects.select_related('coach').all()
    return render(request, 'auth/user_list.html', {
        'user': request.current_user,
        'users': users,
        'total': users.count(),
    })


@admin_required
def user_create(request):
    coaches = Coach.objects.filter(status='active', user_account__isnull=True)
    print("coaches: ",coaches)
    if request.method == 'POST':
        username  = request.POST.get('username', '').strip()
        password  = request.POST.get('password', '').strip()
        password2 = request.POST.get('password2', '').strip()
        role      = request.POST.get('role', 'coach')
        full_name = request.POST.get('full_name', '').strip()
        email     = request.POST.get('email', '').strip()
        coach_id  = request.POST.get('coach_id', '')

        errs = validate_user_create(request.POST)
        if SystemUser.objects.filter(username=username).exists():
            errs.setdefault('username', []).append('Username is already taken.')
        if errs:
            for msg in collect(errs): messages.error(request, msg)
        else:
            su = SystemUser(username=username, role=role, full_name=full_name, email=email)
            su.set_password(password)  # ← PBKDF2 encrypted
            if coach_id and role == 'coach':
                try:
                    su.coach = Coach.objects.get(pk=coach_id)
                except Coach.DoesNotExist:
                    pass
            su.save()

            # Default permissions for coach
            if role == 'coach':
                defaults = ['dashboard', 'student_list', 'attendance']
                for mod in defaults:
                    CoachPermission.objects.get_or_create(user=su, module=mod, defaults={'allowed': True})

            _log('coach_add', f'User account created for {su.full_name}', f'Role: {role}')
            messages.success(request, f'User "{username}" created successfully!')
            return redirect('user_permissions', pk=su.pk) if role == 'coach' else redirect('user_list')

    return render(request, 'auth/user_create.html', {
        'user': request.current_user,
        'coaches': coaches,
    })


@admin_required
def user_permissions(request, pk):
    target_user = get_object_or_404(SystemUser, pk=pk)
    all_modules = CoachPermission.MODULE_CHOICES

    if request.method == 'POST':
        allowed_modules = request.POST.getlist('modules')
        # Reset all then set
        CoachPermission.objects.filter(user=target_user).delete()
        for mod, _ in all_modules:
            CoachPermission.objects.create(
                user=target_user, module=mod,
                allowed=(mod in allowed_modules)
            )
        messages.success(request, f'Permissions updated for {target_user.full_name}.')
        return redirect('user_list')

    existing = {p.module: p.allowed for p in CoachPermission.objects.filter(user=target_user)}
    modules_with_state = [(mod, lbl, existing.get(mod, False)) for mod, lbl in all_modules]

    return render(request, 'auth/user_permissions.html', {
        'user': request.current_user,
        'target_user': target_user,
        'modules': modules_with_state,
    })


@admin_required
@require_POST
def user_reset_password(request, pk):
    target = get_object_or_404(SystemUser, pk=pk)
    new_pw = request.POST.get('new_password', '').strip()
    errs = validate_password_reset(request.POST)
    if errs:
        for msg in collect(errs): messages.error(request, msg)
        return redirect('user_list')
    else:
        target.set_password(new_pw)
        target.save(update_fields=['password_hash'])
        messages.success(request, f'Password reset for {target.full_name}.')
    return redirect('user_list')


@admin_required
@require_POST
def user_toggle(request, pk):
    target = get_object_or_404(SystemUser, pk=pk)
    if target == request.current_user:
        return JsonResponse({'error': 'Cannot deactivate yourself.'}, status=400)
    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])
    return JsonResponse({'is_active': target.is_active, 'message': f'{target.full_name} {"activated" if target.is_active else "deactivated"}.'})


# ════════════════════════════════════════════════════════════════════
#  COACH ATTENDANCE
# ════════════════════════════════════════════════════════════════════

@login_required
@permission_required('attendance')
def coach_attendance(request):
    today      = date.today()
    sel_date   = request.GET.get('date', str(today))
    try:
        sel_date_obj = date.fromisoformat(sel_date)
    except ValueError:
        sel_date_obj = today

    coaches    = Coach.objects.filter(status='active').prefetch_related('sports_coached')
    attendance = {a.coach_id: a for a in CoachAttendance.objects.filter(date=sel_date_obj)}

    if request.method == 'POST':
        marked_by = request.current_user
        for coach in coaches:
            status     = request.POST.get(f'status_{coach.pk}', 'absent')
            check_in   = request.POST.get(f'checkin_{coach.pk}', '') or None
            check_out  = request.POST.get(f'checkout_{coach.pk}', '') or None
            notes_val  = request.POST.get(f'notes_{coach.pk}', '')
            CoachAttendance.objects.update_or_create(
                coach=coach, date=sel_date_obj,
                defaults={
                    'status': status, 'check_in_time': check_in,
                    'check_out_time': check_out, 'method': 'manual',
                    'marked_by': marked_by, 'notes': notes_val,
                }
            )
        _log('attendance', f'Coach attendance marked for {sel_date_obj}',
             f'Marked by {marked_by.full_name}')
        messages.success(request, f'Coach attendance saved for {sel_date_obj}.')
        return redirect(f'{request.path}?date={sel_date_obj}')

    coach_rows = []
    for c in coaches:
        att = attendance.get(c.pk)
        coach_rows.append({'coach': c, 'attendance': att})

    return render(request, 'attendance/coach_attendance.html', {
        'user':        request.current_user,
        'coach_rows':  coach_rows,
        'sel_date':    sel_date_obj,
        'today':       today,
        'att_status_choices': CoachAttendance.STATUS_CHOICES,
    })


# ════════════════════════════════════════════════════════════════════
#  STUDENT ATTENDANCE
# ════════════════════════════════════════════════════════════════════

@login_required
@permission_required('attendance')
def student_attendance(request):
    today      = date.today()
    sel_date   = request.GET.get('date', str(today))
    sel_sport  = request.GET.get('sport', '')
    sel_batch  = request.GET.get('batch', '')

    try:
        sel_date_obj = date.fromisoformat(sel_date)
    except ValueError:
        sel_date_obj = today

    student_qs = StudentData.objects.filter(status='active').select_related(
        'sport', 'batch', 'expertise_level', 'assigned_coach'
    )
    if request.current_user.is_coach and request.current_user.coach:
        student_qs = student_qs.filter(assigned_coach=request.current_user.coach)
    if sel_sport:
        student_qs = student_qs.filter(sport_id=sel_sport)
    if sel_batch:
        student_qs = student_qs.filter(batch_id=sel_batch)

    # Keyed by StudentData integer PK — matches s.pk in the loop below
    attendance = {
        a.student_id: a
        for a in StudentAttendance.objects.filter(date=sel_date_obj)
    }

    if request.method == 'POST':
        marked_by = request.current_user
        for student in student_qs:
            status    = request.POST.get(f'status_{student.pk}', 'not_marked')
            if status == 'not_marked':
                continue  # ← skip students whose attendance wasn't explicitly marked
            notes_val = request.POST.get(f'notes_{student.pk}', '')
            # Strip empty strings → None so TimeField accepts them
            checkin   = request.POST.get(f'checkin_{student.pk}') or None
            checkout  = request.POST.get(f'checkout_{student.pk}') or None

            StudentAttendance.objects.update_or_create(
                student=student,
                date=sel_date_obj,
                defaults={
                    'status':         status,
                    'method':         'manual',
                    'assigned_slot':  student.time_slot,
                    'marked_by':      marked_by,
                    'notes':          notes_val,
                    'check_in_time':  checkin,
                    'check_out_time': checkout,
                }
            )
        _log(
            'attendance',
            f'Student attendance marked for {sel_date_obj}',
            f'Marked by {marked_by.full_name}',
        )
        messages.success(request, f'Student attendance saved for {sel_date_obj}.')
        return redirect(request.get_full_path())

    student_rows = []
    for s in student_qs:
        att = attendance.get(s.pk)   # s.pk == StudentAttendance.student_id (FK int)
        student_rows.append({'student': s, 'attendance': att})

    return render(request, 'attendance/student_attendance.html', {
        'user':              request.current_user,
        'student_rows':      student_rows,
        'sel_date':          sel_date_obj,
        'today':             today,
        'sports':            Sport.objects.filter(is_active=True),
        'batches':           Batch.objects.filter(is_active=True),
        'sel_sport':         sel_sport,
        'sel_batch':         sel_batch,
        'total':             len(student_rows),
        'att_status_choices': StudentAttendance.STATUS_CHOICES,
    })
    
    
@login_required
@permission_required('attendance')
def coach_attendance_history(request):
    today = date.today()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))

    # Clamp
    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    _, days_in_month = monthrange(year, month)
    sel_coach_id = request.GET.get('coach', '')
    coaches = Coach.objects.filter(status='active').prefetch_related('sports_coached')

    att_qs = CoachAttendance.objects.filter(
        date__year=year, date__month=month
    ).select_related('coach', 'marked_by')
    if sel_coach_id:
        att_qs = att_qs.filter(coach_id=sel_coach_id)

    # Build {coach_pk: {day_int: record}}
    raw = {}
    for a in att_qs:
        raw.setdefault(a.coach_id, {})[a.date.day] = a

    STATUS_LABEL = {'present':'P','absent':'A','late':'L','on_leave':'OL'}
    STATUS_CLASS = {'present':'dc-present','absent':'dc-absent',
                    'late':'dc-late','on_leave':'dc-on_leave'}

    coach_rows = []
    for c in coaches:
        if sel_coach_id and str(c.pk) != sel_coach_id:
            continue
        day_cells = []
        for d in range(1, days_in_month + 1):
            rec = raw.get(c.pk, {}).get(d)
            is_future = date(year, month, d) > today
            if is_future:
                day_cells.append({'label':'', 'css':'dc-future', 'title':'Future'})
            elif rec:
                day_cells.append({
                    'label':  STATUS_LABEL.get(rec.status, '?'),
                    'css':    STATUS_CLASS.get(rec.status, 'dc-none'),
                    'title':  rec.get_status_display(),
                    'method': rec.method,
                })
            else:
                day_cells.append({'label':'', 'css':'dc-none', 'title':'Not marked'})

        day_map   = raw.get(c.pk, {})
        present   = sum(1 for r in day_map.values() if r.status == 'present')
        absent    = sum(1 for r in day_map.values() if r.status == 'absent')
        late      = sum(1 for r in day_map.values() if r.status == 'late')
        on_leave  = sum(1 for r in day_map.values() if r.status == 'on_leave')
        pct       = round(present / days_in_month * 100) if days_in_month else 0

        coach_rows.append({
            'coach':     c,
            'day_cells': day_cells,
            'present':   present,
            'absent':    absent,
            'late':      late,
            'on_leave':  on_leave,
            'pct':       pct,
        })

    prev_month = month - 1 if month > 1 else 12
    prev_year  = year     if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year  = year     if month < 12 else year + 1
    can_go_next = date(next_year, next_month, 1) <= today.replace(day=1)

    return render(request, 'attendance/coach_attendance_history.html', {
        'user':          request.current_user,
        'coach_rows':    coach_rows,
        'coaches':       coaches,
        'sel_coach_id':  sel_coach_id,
        'year':          year,
        'month':         month,
        'month_name':    date(year, month, 1).strftime('%B %Y'),
        'days_in_month': days_in_month,
        'day_range':     range(1, days_in_month + 1),
        'today':         today,
        'prev_month':    prev_month,
        'prev_year':     prev_year,
        'next_month':    next_month,
        'next_year':     next_year,
        'can_go_next':   can_go_next,
    })


@login_required
@permission_required('attendance')
def student_attendance_history(request):
    today = date.today()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))

    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    _, days_in_month = monthrange(year, month)
    sel_sport   = request.GET.get('sport', '')
    sel_batch   = request.GET.get('batch', '')
    sel_student = request.GET.get('student', '')

    student_qs = StudentData.objects.filter(status='active').select_related(
        'sport', 'batch', 'expertise_level'
    )
    if request.current_user.is_coach and request.current_user.coach:
        student_qs = student_qs.filter(assigned_coach=request.current_user.coach)
    if sel_sport:   student_qs = student_qs.filter(sport_id=sel_sport)
    if sel_batch:   student_qs = student_qs.filter(batch_id=sel_batch)
    if sel_student: student_qs = student_qs.filter(pk=sel_student)

    att_qs = StudentAttendance.objects.filter(
        date__year=year, date__month=month,
        student__in=student_qs
    ).select_related('student')

    raw = {}
    for a in att_qs:
        raw.setdefault(a.student_id, {})[a.date.day] = a

    STATUS_LABEL = {'present':'P','absent':'A','late':'L','excused':'Ex'}
    STATUS_CLASS = {'present':'dc-present','absent':'dc-absent',
                    'late':'dc-late','excused':'dc-excused'}

    student_rows = []
    for s in student_qs:
        day_cells = []
        for d in range(1, days_in_month + 1):
            rec = raw.get(s.pk, {}).get(d)
            is_future = date(year, month, d) > today
            if is_future:
                day_cells.append({'label':'', 'css':'dc-future', 'title':'Future'})
            elif rec:
                day_cells.append({
                    'label':  STATUS_LABEL.get(rec.status, '?'),
                    'css':    STATUS_CLASS.get(rec.status, 'dc-none'),
                    'title':  rec.get_status_display(),
                    'method': rec.method,
                })
            else:
                day_cells.append({'label':'', 'css':'dc-none', 'title':'Not marked'})

        day_map  = raw.get(s.pk, {})
        present  = sum(1 for r in day_map.values() if r.status == 'present')
        absent   = sum(1 for r in day_map.values() if r.status == 'absent')
        late     = sum(1 for r in day_map.values() if r.status == 'late')
        excused  = sum(1 for r in day_map.values() if r.status == 'excused')
        pct      = round(present / days_in_month * 100) if days_in_month else 0

        student_rows.append({
            'student':   s,
            'day_cells': day_cells,
            'present':   present,
            'absent':    absent,
            'late':      late,
            'excused':   excused,
            'pct':       pct,
        })

    prev_month = month - 1 if month > 1 else 12
    prev_year  = year     if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year  = year     if month < 12 else year + 1
    can_go_next = date(next_year, next_month, 1) <= today.replace(day=1)

    return render(request, 'attendance/student_attendance_history.html', {
        'user':          request.current_user,
        'student_rows':  student_rows,
        'sports':        Sport.objects.filter(is_active=True),
        'batches':       Batch.objects.filter(is_active=True),
        'all_students':  StudentData.objects.filter(status='active').select_related('sport'),
        'sel_sport':     sel_sport,
        'sel_batch':     sel_batch,
        'sel_student':   sel_student,
        'year':          year,
        'month':         month,
        'month_name':    date(year, month, 1).strftime('%B %Y'),
        'days_in_month': days_in_month,
        'day_range':     range(1, days_in_month + 1),
        'today':         today,
        'prev_month':    prev_month,
        'prev_year':     prev_year,
        'next_month':    next_month,
        'next_year':     next_year,
        'can_go_next':   can_go_next,
    })

# ════════════════════════════════════════════════════════════════════
#  QR ATTENDANCE SCAN  (AJAX endpoint — called from scan page)
# ════════════════════════════════════════════════════════════════════

@login_required
@permission_required('attendance')
def qr_scan_page(request):
    return render(request, 'attendance/qr_scan.html', {'user': request.current_user})


@login_required
@permission_required('attendance')
@require_POST
def qr_mark_attendance(request):
    """
    POST body: { "qr_data": "<json string from QR>", "type": "student"|"coach" }
    Returns JSON with result.
    """
    try:
        body     = json.loads(request.body)
        qr_raw   = body.get('qr_data', '')
        qr_obj   = json.loads(qr_raw)
        entity_type = qr_obj.get('type', '')
        entity_id   = qr_obj.get('id', '')
        today       = date.today()
        now_time    = timezone.now().time()
        marked_by   = request.current_user

        if entity_type == 'student':
            student = StudentData.objects.get(student_id=entity_id)
            att, created = StudentAttendance.objects.update_or_create(
                student=student, date=today,
                defaults={
                    'status': 'present', 'method': 'qr',
                    'assigned_slot': student.time_slot,
                    'marked_by': marked_by,
                }
            )
            return JsonResponse({
                'success': True,
                'message': f'✓ {student.full_name} marked Present',
                'id': student.student_id,
                'name': student.full_name,
                'sport': student.sport.name,
                'photo': student.photo.url if student.photo else None,
                'already_marked': not created,
            })

        elif entity_type == 'coach':
            coach = Coach.objects.get(coach_id=entity_id)
            att, created = CoachAttendance.objects.update_or_create(
                coach=coach, date=today,
                defaults={
                    'status': 'present', 'check_in_time': now_time,
                    'method': 'qr', 'marked_by': marked_by,
                }
            )
            return JsonResponse({
                'success': True,
                'message': f'✓ Coach {coach.full_name} checked in',
                'id': coach.coach_id,
                'name': coach.full_name,
                'photo': coach.photo.url if coach.photo else None,
                'already_marked': not created,
            })

        else:
            return JsonResponse({'success': False, 'message': 'Unrecognised QR code.'})

    except (StudentData.DoesNotExist, Coach.DoesNotExist):
        return JsonResponse({'success': False, 'message': 'Person not found in the system.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'})


# ════════════════════════════════════════════════════════════════════
#  STUDENT VIEWS
# ════════════════════════════════════════════════════════════════════

@login_required
@permission_required('student_list')
def student_list(request):
    qs = StudentData.objects.select_related('sport','batch','expertise_level','duration','assigned_coach')
    print("student list: ",qs)
    user = request.current_user
    if user.is_coach and user.coach:
        qs = qs.filter(assigned_coach=user.coach)

    # ── Auto-sync expired status ──────────────────────────────
    today = timezone.now().date()
    StudentData.objects.filter(
        status='active',
        subscription_expiry__lte=today
    ).update(status='expired')
    # ─────────────────────────────────────────────────────────
    search = request.GET.get('q', '').strip()
    sport  = request.GET.get('sport', '')
    status = request.GET.get('status', '')
    batch  = request.GET.get('batch', '')

    if search:
        qs = qs.filter(Q(first_name__icontains=search)|Q(last_name__icontains=search)|
                       Q(student_id__icontains=search)|Q(contact_number__icontains=search))
    if sport:  qs = qs.filter(sport_id=sport)
    if status: qs = qs.filter(status=status)
    if batch:  qs = qs.filter(batch_id=batch)
    student_statuses = [
    {
        "id": s.student_id,
        "name": s.first_name,
        "status": s.status
    }
    for s in qs
    ]

    print("all_statuses: ",student_statuses)
    return render(request, 'students/student_list.html', {
        'user': user, 'students': qs,
        'sports': Sport.objects.filter(is_active=True),
        'batches': Batch.objects.filter(is_active=True),
        'total': qs.count(), 'search': search,
        'sel_sport': sport, 'sel_status': status, 'sel_batch': batch,
    })


@login_required
@permission_required('student_list')
def student_detail(request, pk):
    """
    Full profile page for a single student:
      - Personal & parent details
      - Sport / batch / fee breakdown
      - Subscription timeline
      - Last-30-day attendance summary
      - WhatsApp notify panel
    """
    student = get_object_or_404(
        StudentData.objects.select_related(
            'sport', 'batch', 'expertise_level', 'duration',
            'fee_structure', 'assigned_coach'
        ),
        pk=pk
    )

    # ── Permission: coaches see only their own students ──
    if request.current_user.is_coach and request.current_user.coach:
        if student.assigned_coach != request.current_user.coach:
            messages.error(request, 'You do not have access to this student.')
            return redirect('student_list')

    # ── Attendance: last 30 days ──
    today      = date.today()
    thirty_ago = today - timedelta(days=30)
    recent_attendance = (
        StudentAttendance.objects
        .filter(student=student, date__gte=thirty_ago)
        .order_by('-date')[:15]
    )
    att_present = sum(1 for a in recent_attendance if a.status == 'present')
    att_absent  = sum(1 for a in recent_attendance if a.status == 'absent')
    att_late    = sum(1 for a in recent_attendance if a.status == 'late')
    marked_days = len(recent_attendance)
    att_pct     = round(att_present / marked_days * 100) if marked_days else 0

    # ── Fee paid percentage (for progress bar) ──
    try:
        fee_paid_pct = round(float(student.fee_paid) / float(student.total_fee) * 100) if student.total_fee else 0
        fee_paid_pct = min(fee_paid_pct, 100)
    except Exception:
        fee_paid_pct = 0

    # ── Subscription progress bar (% of time elapsed) ──
    try:
        total_days = (student.subscription_expiry - student.subscription_start).days or 1
        elapsed    = (today - student.subscription_start).days
        sub_progress_pct = min(max(round(elapsed / total_days * 100), 0), 100)
    except Exception:
        sub_progress_pct = 0

    # ── WhatsApp phone — normalise to international format ──
    raw_phone = student.parent_whatsapp.strip()
    clean_phone = ''.join(filter(str.isdigit, raw_phone))
    if len(clean_phone) == 10:
        clean_phone = '91' + clean_phone        # India: add country code
    elif clean_phone.startswith('0'):
        clean_phone = '91' + clean_phone[1:]

    return render(request, 'students/student_detail.html', {
        'user':              request.current_user,
        'student':           student,
        'recent_attendance': recent_attendance,
        'att_present':       att_present,
        'att_absent':        att_absent,
        'att_late':          att_late,
        'att_pct':           att_pct,
        'fee_paid_pct':      fee_paid_pct,
        'sub_progress_pct':  sub_progress_pct,
        'wa_phone':          clean_phone,
        'today':             today,
    })


@login_required
@permission_required('student_admission')
@require_GET
def get_fee(request):
    try:
        fee = FeeStructures.objects.get(
            sport_id=request.GET['sport'], batch_id=request.GET['batch'],
            expertise_level_id=request.GET['level'], duration_id=request.GET['duration'], is_active=True,
        )
        return JsonResponse({'found':True,'fee_id':fee.pk,'fee_amount':float(fee.fee_amount),
            'discount_pct':float(fee.discount_pct),'discounted_amount':fee.discounted_amount})
    except FeeStructures.DoesNotExist:
        return JsonResponse({'found':False})


@login_required
@permission_required('student_admission')
def student_admission(request):
    # ── Edit mode: fetch existing student if ?edit=pk is passed ──────
    edit_pk = request.GET.get('edit') or request.POST.get('edit_pk')
    student_obj = None
    if edit_pk:
        try:
            student_obj = StudentData.objects.get(pk=edit_pk)
        except StudentData.DoesNotExist:
            student_obj = None

    if request.method == 'POST':
        first_name        = request.POST.get('first_name', '').strip()
        last_name         = request.POST.get('last_name', '').strip()
        dob               = request.POST.get('dob', '')
        gender            = request.POST.get('gender', '')
        blood_group       = request.POST.get('blood_group', 'NK')
        contact_number    = request.POST.get('contact_number', '').strip()
        email             = request.POST.get('email', '').strip()
        address           = request.POST.get('address', '').strip()
        parent_name       = request.POST.get('parent_name', '').strip()
        parent_relation   = request.POST.get('parent_relation', 'Father')
        parent_whatsapp   = request.POST.get('parent_whatsapp', '').strip()
        parent_email      = request.POST.get('parent_email', '').strip()
        parent_occupation = request.POST.get('parent_occupation', '').strip()
        emergency_contact = request.POST.get('emergency_contact', '').strip()
        sport_id          = request.POST.get('sport')
        batch_id          = request.POST.get('batch')
        level_id          = request.POST.get('expertise_level')
        duration_id       = request.POST.get('duration')
        coach_id          = request.POST.get('assigned_coach', '')
        time_slot         = request.POST.get('time_slot', '').strip()
        admission_date_str= request.POST.get('admission_date', str(date.today()))
        fee_id            = request.POST.get('fee_id', '')
        fee_paid_decimal  = Decimal(request.POST.get('fee_paid', '0') or '0')

        errs = {}
        errs.update(validate_student_personal(request.POST))
        errs.update(validate_student_parent(request.POST))
        errs.update(validate_student_sport(request.POST))

        if errs:
            for msg in collect(errs):
                messages.error(request, msg)
        else:
            try:
                dur_obj    = Duration.objects.get(pk=duration_id)
                months     = int(dur_obj.duration_name.split()[0])
                adm_date   = date.fromisoformat(admission_date_str)
                sub_expiry = adm_date + relativedelta(months=months)
            except Exception as e:
                print("ERROR:", e)
                adm_date   = date.today()
                sub_expiry = adm_date + timedelta(days=30)

            total_fee = Decimal('0')
            fee_obj   = None
            if fee_id:
                try:
                    fee_obj   = FeeStructures.objects.get(pk=fee_id)
                    total_fee = Decimal(str(fee_obj.discounted_amount))
                except FeeStructures.DoesNotExist:
                    pass

            assigned_coach = None
            if coach_id:
                try:
                    assigned_coach = Coach.objects.get(pk=coach_id)
                except Coach.DoesNotExist:
                    pass

            # ── EDIT mode: update existing student ────────────────────
            if student_obj:
                student_obj.first_name        = first_name
                student_obj.last_name         = last_name
                student_obj.dob               = dob
                student_obj.gender            = gender
                student_obj.blood_group       = blood_group
                student_obj.contact_number    = contact_number
                student_obj.email             = email
                student_obj.address           = address
                student_obj.parent_name       = parent_name
                student_obj.parent_relation   = parent_relation
                student_obj.parent_whatsapp   = parent_whatsapp
                student_obj.parent_email      = parent_email
                student_obj.parent_occupation = parent_occupation
                student_obj.emergency_contact = emergency_contact
                student_obj.sport_id          = sport_id
                student_obj.batch_id          = batch_id
                student_obj.expertise_level_id= level_id
                student_obj.duration_id       = duration_id
                student_obj.fee_structure     = fee_obj
                student_obj.assigned_coach    = assigned_coach
                student_obj.time_slot         = time_slot
                student_obj.admission_date    = adm_date
                student_obj.subscription_start= adm_date
                student_obj.subscription_expiry= sub_expiry
                student_obj.total_fee         = total_fee
                if 'photo' in request.FILES:
                    student_obj.photo = request.FILES['photo']
                student_obj.save()

                _log(
                    'admission',
                    f'{student_obj.full_name} profile updated',
                    f'ID:{student_obj.student_id}',
                    student=student_obj,
                )
                messages.success(request, f'{student_obj.full_name}\'s profile updated successfully.')
                return redirect('student_detail', pk=student_obj.pk)

            # ── CREATE mode: new student ──────────────────────────────
            else:
                student = StudentData.objects.create(
                    first_name=first_name, last_name=last_name, dob=dob, gender=gender,
                    blood_group=blood_group, contact_number=contact_number,
                    email=email, address=address,
                    parent_name=parent_name, parent_relation=parent_relation,
                    parent_whatsapp=parent_whatsapp, parent_email=parent_email,
                    parent_occupation=parent_occupation, emergency_contact=emergency_contact,
                    sport_id=sport_id, batch_id=batch_id, expertise_level_id=level_id,
                    duration_id=duration_id, fee_structure=fee_obj,
                    assigned_coach=assigned_coach,
                    admission_date=adm_date, subscription_start=adm_date,
                    subscription_expiry=sub_expiry, time_slot=time_slot,
                    total_fee=total_fee,
                    fee_paid=Decimal('0'),
                    fee_due=total_fee,
                )

                if 'photo' in request.FILES:
                    student.photo = request.FILES['photo']
                    student.save()

                if fee_paid_decimal > 0:
                    Payment.objects.create(
                        student=student,
                        amount=fee_paid_decimal,
                        payment_mode='cash',
                        payment_date=adm_date,
                        note=f'Admission payment — {student.sport.name} ({student.duration.duration_name})',
                        recorded_by=request.current_user,
                    )

                _log(
                    'admission',
                    f'{student.full_name} enrolled in {student.sport.name}',
                    f'ID:{student.student_id}',
                    student=student,
                )
                return redirect('admission_success', pk=student.pk)

    # ── GET: render form (pre-filled if edit mode) ────────────────────
    return render(request, 'students/admission.html', {
        'user':         request.current_user,
        'sports':       Sport.objects.filter(is_active=True),
        'batches':      Batch.objects.filter(is_active=True),
        'levels':       ExpertiseLevel.objects.filter(is_active=True),
        'durations':    Duration.objects.filter(is_active=True),
        'coaches':      Coach.objects.filter(status='active'),
        'today':        date.today().isoformat(),
        'edit_student': student_obj,   # ← None for new admission, object for edit
    })

@login_required
def admission_success(request,pk):
    student=get_object_or_404(StudentData.objects.select_related(
        'sport','batch','expertise_level','duration','fee_structure','assigned_coach'),pk=pk)
    return render(request,'students/admission_success.html',{
        'user':request.current_user,'student':student})


# ════════════════════════════════════════════════════════════════════
#  COACH VIEWS
# ════════════════════════════════════════════════════════════════════

@login_required
@permission_required('coach_list')
def coach_list(request):
    qs=Coach.objects.prefetch_related('sports_coached','expertise_levels')
    search=request.GET.get('q','').strip(); sport=request.GET.get('sport','')
    status=request.GET.get('status',''); emp=request.GET.get('emp_type','')
    if search: qs=qs.filter(Q(first_name__icontains=search)|Q(last_name__icontains=search)|Q(coach_id__icontains=search))
    if sport:  qs=qs.filter(sports_coached__id=sport)
    if status: qs=qs.filter(status=status)
    if emp:    qs=qs.filter(employment_type=emp)
    return render(request,'coaches/coach_list.html',{
        'user':request.current_user,'coaches':qs,
        'sports':Sport.objects.filter(is_active=True),
        'total':Coach.objects.count(),'active_count':Coach.objects.filter(status='active').count(),
        'employment_choices':Coach.EMPLOYMENT_TYPE_CHOICES,
        'search':search,'sel_sport':sport,'sel_status':status,'sel_emp':emp,
    })


@admin_required
def coach_add(request):
    sports=Sport.objects.filter(is_active=True); levels=ExpertiseLevel.objects.filter(is_active=True)
    if request.method=='POST':
        first_name=request.POST.get('first_name','').strip()
        last_name=request.POST.get('last_name','').strip()
        dob=request.POST.get('dob','') or None
        gender=request.POST.get('gender','')
        contact_number=request.POST.get('contact_number','').strip()
        joining_date=request.POST.get('joining_date','')

        # Login credentials
        create_login=request.POST.get('create_login')=='on'
        username=request.POST.get('username','').strip()
        password=request.POST.get('password','').strip()

        errs = validate_coach(request.POST)
        if create_login:
            login_errs = validate_user_create({'username':username,'password':password,'password2':password,'full_name':first_name+' '+last_name,'role':'coach'})
            # Merge
            for k,v in login_errs.items():
                errs.setdefault(k, v)
            if username and SystemUser.objects.filter(username=username).exists():
                errs['username'] = [f'Username "{username}" is already taken.']

        if errs:
            for msg in collect(errs): messages.error(request, msg)
        else:
            coach=Coach.objects.create(
                first_name=first_name,last_name=last_name,dob=dob,gender=gender,
                contact_number=contact_number,
                whatsapp_number=request.POST.get('whatsapp_number','').strip(),
                email=request.POST.get('email','').strip(),
                address=request.POST.get('address','').strip(),
                qualification=request.POST.get('qualification','').strip(),
                experience_years=int(request.POST.get('experience_years','0') or 0),
                joining_date=joining_date,
                employment_type=request.POST.get('employment_type','full_time'),
                salary_type=request.POST.get('salary_type','fixed'),
                salary_amount=float(request.POST.get('salary_amount','0') or 0),
                emergency_name=request.POST.get('emergency_name','').strip(),
                emergency_phone=request.POST.get('emergency_phone','').strip(),
                emergency_relation=request.POST.get('emergency_relation','').strip(),
                notes=request.POST.get('notes','').strip(),
            )
            sport_ids=request.POST.getlist('sports_coached')
            level_ids=request.POST.getlist('expertise_levels')
            if sport_ids: coach.sports_coached.set(sport_ids)
            if level_ids: coach.expertise_levels.set(level_ids)
            for field in ['photo','id_proof','certificate']:
                if field in request.FILES: setattr(coach,field,request.FILES[field])
            coach.save()

            # Create login if requested
            if create_login:
                su=SystemUser(username=username,role='coach',full_name=coach.full_name,
                              email=coach.email,coach=coach)
                su.set_password(password)
                su.save()
                # Default permissions
                for mod in ['dashboard','student_list','attendance']:
                    CoachPermission.objects.get_or_create(user=su,module=mod,defaults={'allowed':True})
                messages.success(request,f'Coach {coach.full_name} added with login credentials!')
            else:
                messages.success(request,f'Coach {coach.full_name} added!')

            _log('coach_add',f'Coach {coach.full_name} added',f'ID:{coach.coach_id}')
            return redirect('coach_list')

    return render(request,'coaches/coach_add.html',{
        'user':request.current_user,'sports':sports,'levels':levels,
        'employment_choices':Coach.EMPLOYMENT_TYPE_CHOICES,
        'salary_choices':Coach.SALARY_TYPE_CHOICES,
        'today':str(date.today()),
    })


@login_required
def coach_detail(request,pk):
    coach=get_object_or_404(Coach.objects.prefetch_related('sports_coached','expertise_levels','students'),pk=pk)
    students=coach.students.select_related('sport','batch','expertise_level').filter(status='active')
    try: user_account=coach.user_account
    except: user_account=None

    # Recent attendance
    recent_att=CoachAttendance.objects.filter(coach=coach).order_by('-date')[:10]

    return render(request,'coaches/coach_detail.html',{
        'user':request.current_user,'coach':coach,
        'students':students,'user_account':user_account,'recent_att':recent_att,
    })


@admin_required
def coach_edit(request,pk):
    coach=get_object_or_404(Coach,pk=pk)
    if request.method=='POST':
        coach.first_name=request.POST.get('first_name','').strip()
        coach.last_name=request.POST.get('last_name','').strip()
        coach.dob=request.POST.get('dob','') or None
        coach.gender=request.POST.get('gender',coach.gender)
        coach.contact_number=request.POST.get('contact_number','').strip()
        coach.whatsapp_number=request.POST.get('whatsapp_number','').strip()
        coach.email=request.POST.get('email','').strip()
        coach.address=request.POST.get('address','').strip()
        coach.qualification=request.POST.get('qualification','').strip()
        coach.experience_years=int(request.POST.get('experience_years',0) or 0)
        coach.joining_date=request.POST.get('joining_date',coach.joining_date)
        coach.employment_type=request.POST.get('employment_type',coach.employment_type)
        coach.salary_type=request.POST.get('salary_type',coach.salary_type)
        coach.salary_amount=float(request.POST.get('salary_amount',0) or 0)
        coach.emergency_name=request.POST.get('emergency_name','').strip()
        coach.emergency_phone=request.POST.get('emergency_phone','').strip()
        coach.emergency_relation=request.POST.get('emergency_relation','').strip()
        coach.notes=request.POST.get('notes','').strip()
        coach.status=request.POST.get('status',coach.status)
        coach.sports_coached.set(request.POST.getlist('sports_coached'))
        coach.expertise_levels.set(request.POST.getlist('expertise_levels'))
        for f in ['photo','id_proof','certificate']:
            if f in request.FILES: setattr(coach,f,request.FILES[f])
        coach.save()
        messages.success(request,f'{coach.full_name} updated!')
        return redirect('coach_detail',pk=coach.pk)

    return render(request,'coaches/coach_add.html',{
        'user':request.current_user,'coach':coach,
        'sports':Sport.objects.filter(is_active=True),
        'levels':ExpertiseLevel.objects.filter(is_active=True),
        'employment_choices':Coach.EMPLOYMENT_TYPE_CHOICES,
        'salary_choices':Coach.SALARY_TYPE_CHOICES,
        'is_edit':True,'today':str(date.today()),
    })


@admin_required
@require_POST
def coach_delete(request,pk):
    coach=get_object_or_404(Coach,pk=pk)
    name=coach.full_name; coach.delete()
    messages.success(request,f'Coach {name} removed.')
    return redirect('coach_list')


@admin_required
@require_POST
def coach_toggle_status(request,pk):
    coach=get_object_or_404(Coach,pk=pk)
    coach.is_active=not coach.is_active
    coach.status='active' if coach.is_active else 'inactive'
    coach.save()
    return JsonResponse({'is_active':coach.is_active,'label':coach.status_label,
        'message':f'{coach.full_name} marked {coach.status_label}.'})


# ════════════════════════════════════════════════════════════════════
#  MASTER VIEWS (sport, batch, level, fee)
# ════════════════════════════════════════════════════════════════════

ICON_CHOICES=[('🏸','Badminton'),('🎾','Tennis'),('⚽','Football'),('⛸️','Skating'),
    ('♟️','Chess'),('🏊','Swimming'),('🏓','Table Tennis'),('🥊','Boxing'),('🤸','Gymnastics'),
    ('🏋️','Weightlifting'),('🎯','Archery'),('🏐','Volleyball'),('🏀','Basketball'),
    ('🎱','Billiards'),('🥋','Martial Arts')]

@login_required
@admin_required
def sports_master(request):
    if request.method=='POST':
        name=request.POST.get('name','').strip(); icon=request.POST.get('icon','🏸')
        desc=request.POST.get('description','').strip(); ia=request.POST.get('is_active')=='on'
        if not name: messages.error(request,'Name required.')
        elif Sport.objects.filter(name__iexact=name).exists(): messages.error(request,f'"{name}" exists.')
        else: Sport.objects.create(name=name,icon=icon,description=desc,is_active=ia); messages.success(request,f'"{name}" added!'); return redirect('sports_master')
    sports=Sport.objects.all()
    return render(request,'masters/sports_master.html',{'user':request.current_user,'sports':sports,'icon_choices':ICON_CHOICES,'total':sports.count(),'active_count':sports.filter(is_active=True).count(),'inactive_count':sports.filter(is_active=False).count()})

@admin_required
def sport_edit(request,pk):
    sport=get_object_or_404(Sport,pk=pk)
    if request.method=='POST':
        name=request.POST.get('name','').strip(); icon=request.POST.get('icon',sport.icon)
        desc=request.POST.get('description','').strip(); ia=request.POST.get('is_active')=='on'
        errs = validate_sport({'name':name,'icon':icon}, existing_pk=pk)
        if errs:
            for msg in collect(errs): messages.error(request, msg)
        else: sport.name=name;sport.icon=icon;sport.description=desc;sport.is_active=ia;sport.save(); messages.success(request,f'"{name}" updated!')
        return redirect('sports_master')

@admin_required
@require_POST
def sport_delete(request,pk):
    s=get_object_or_404(Sport,pk=pk);n=s.name;s.delete();messages.success(request,f'"{n}" deleted.');return redirect('sports_master')

@admin_required
@require_POST
def sport_toggle_status(request,pk):
    s=get_object_or_404(Sport,pk=pk);s.is_active=not s.is_active;s.save()
    return JsonResponse({'status':'ok','is_active':s.is_active,'message':f'"{s.name}" {"Active" if s.is_active else "Inactive"}.'})

BATCH_TYPE_CHOICES=[('regular','Regular'),('alternate','Alternate'),('day_based','Day-Based'),('weekend','Weekend'),('intensive','Intensive'),('custom','Custom')]
DAYS_CHOICES=[(i,f'{i} day{"s" if i>1 else ""} / week') for i in range(1,8)]

@admin_required
def batch_master(request):
    if request.method=='POST':
        name=request.POST.get('name','').strip();bt=request.POST.get('batch_type','regular');days=request.POST.get('days_per_week',6);desc=request.POST.get('description','').strip();ia=request.POST.get('is_active')=='on'
        errs = validate_batch({'name':name,'batch_type':bt,'days_per_week':days})
        if errs:
            for msg in collect(errs): messages.error(request, msg)
        else: Batch.objects.create(name=name,batch_type=bt,days_per_week=int(days),description=desc,is_active=ia);messages.success(request,f'"{name}" added!');return redirect('batch_master')
    batches=Batch.objects.all()
    return render(request,'masters/batch_master.html',{'user':request.current_user,'batches':batches,'batch_type_choices':BATCH_TYPE_CHOICES,'days_choices':DAYS_CHOICES,'total':batches.count(),'active_count':batches.filter(is_active=True).count(),'inactive_count':batches.filter(is_active=False).count()})

@admin_required
def batch_edit(request,pk):
    b=get_object_or_404(Batch,pk=pk)
    if request.method=='POST':
        name=request.POST.get('name','').strip();bt=request.POST.get('batch_type',b.batch_type);days=request.POST.get('days_per_week',b.days_per_week);desc=request.POST.get('description','').strip();ia=request.POST.get('is_active')=='on'
        if Batch.objects.filter(name__iexact=name).exclude(pk=pk).exists(): messages.error(request,'Exists.')
        else: b.name=name;b.batch_type=bt;b.days_per_week=int(days);b.description=desc;b.is_active=ia;b.save();messages.success(request,f'"{name}" updated!')
        return redirect('batch_master')

@admin_required
@require_POST
def batch_delete(request,pk):
    b=get_object_or_404(Batch,pk=pk);n=b.name;b.delete();messages.success(request,f'"{n}" deleted.');return redirect('batch_master')

@admin_required
@require_POST
def batch_toggle_status(request,pk):
    b=get_object_or_404(Batch,pk=pk);b.is_active=not b.is_active;b.save()
    return JsonResponse({'status':'ok','is_active':b.is_active,'message':f'"{b.name}" {"Active" if b.is_active else "Inactive"}.'})

LEVEL_COLOR_CHOICES=[('#3A7A52','Forest Green'),('#2E6B9E','Ocean Blue'),('#C47A30','Amber'),('#B84040','Red'),('#6A3DAA','Purple'),('#C4973A','Gold'),('#1A1612','Ink Black'),('#8A8480','Slate')]

@admin_required
def expertise_level_master(request):
    if request.method=='POST':
        name=request.POST.get('name','').strip();order=request.POST.get('order',1);color=request.POST.get('color_hex','#3A7A52');desc=request.POST.get('description','').strip();ia=request.POST.get('is_active')=='on'
        if not name: messages.error(request,'Required.')
        elif ExpertiseLevel.objects.filter(name__iexact=name).exists(): messages.error(request,'Exists.')
        else: ExpertiseLevel.objects.create(name=name,order=int(order),color_hex=color,description=desc,is_active=ia);messages.success(request,f'"{name}" added!');return redirect('expertise_level_master')
    levels=ExpertiseLevel.objects.all()
    return render(request,'masters/expertise_level_master.html',{'user':request.current_user,'levels':levels,'color_choices':LEVEL_COLOR_CHOICES,'order_choices':range(1,11),'total':levels.count(),'active_count':levels.filter(is_active=True).count(),'inactive_count':levels.filter(is_active=False).count()})

@admin_required
def expertise_level_edit(request,pk):
    lv=get_object_or_404(ExpertiseLevel,pk=pk)
    if request.method=='POST':
        name=request.POST.get('name','').strip();order=request.POST.get('order',lv.order);color=request.POST.get('color_hex',lv.color_hex);desc=request.POST.get('description','').strip();ia=request.POST.get('is_active')=='on'
        if ExpertiseLevel.objects.filter(name__iexact=name).exclude(pk=pk).exists(): messages.error(request,'Exists.')
        else: lv.name=name;lv.order=int(order);lv.color_hex=color;lv.description=desc;lv.is_active=ia;lv.save();messages.success(request,f'"{name}" updated!')
        return redirect('expertise_level_master')

@admin_required
@require_POST
def expertise_level_delete(request,pk):
    lv=get_object_or_404(ExpertiseLevel,pk=pk);n=lv.name;lv.delete();messages.success(request,f'"{n}" deleted.');return redirect('expertise_level_master')

@admin_required
@require_POST
def expertise_level_toggle(request,pk):
    lv=get_object_or_404(ExpertiseLevel,pk=pk);lv.is_active=not lv.is_active;lv.save()
    return JsonResponse({'status':'ok','is_active':lv.is_active,'message':f'"{lv.name}" {"Active" if lv.is_active else "Inactive"}.'})

@admin_required
def fee_structure(request):
    if request.method=='POST':
        sid=request.POST.get('sport');bid=request.POST.get('batch');lid=request.POST.get('expertise_level');did=request.POST.get('duration')
        amt=request.POST.get('fee_amount','').strip();disc=request.POST.get('discount_pct','0').strip() or '0';edate=request.POST.get('effective_date','').strip();notes=request.POST.get('notes','').strip();ia=request.POST.get('is_active')=='on'
        errs = validate_fee_structure({'sport':sid,'batch':bid,'expertise_level':lid,'duration':did,'fee_amount':amt,'effective_date':edate,'discount_pct':disc})
        if errs:
            for msg in collect(errs): messages.error(request, msg)
        else: FeeStructures.objects.create(sport_id=sid,batch_id=bid,expertise_level_id=lid,duration_id=did,fee_amount=amt,discount_pct=disc,effective_date=edate,notes=notes,is_active=ia);messages.success(request,'Fee added!');return redirect('fee_structure')
    fees=FeeStructures.objects.select_related('sport','batch','expertise_level','duration').all()
    return render(request,'masters/fee_structure.html',{'user':request.current_user,'fees':fees,'sports':Sport.objects.filter(is_active=True),'batches':Batch.objects.filter(is_active=True),'levels':ExpertiseLevel.objects.filter(is_active=True),'durations':Duration.objects.filter(is_active=True),'total':fees.count(),'active_count':fees.filter(is_active=True).count()})

@admin_required
def fee_structure_edit(request,pk):
    fee=get_object_or_404(FeeStructures,pk=pk)
    if request.method=='POST':
        sid=request.POST.get('sport');bid=request.POST.get('batch');lid=request.POST.get('expertise_level');did=request.POST.get('duration')
        if FeeStructures.objects.filter(sport_id=sid,batch_id=bid,expertise_level_id=lid,duration_id=did).exclude(pk=pk).exists(): messages.error(request,'Duplicate.'); return redirect('fee_structure')
        fee.sport_id=sid;fee.batch_id=bid;fee.expertise_level_id=lid;fee.duration_id=did
        fee.fee_amount=request.POST.get('fee_amount',fee.fee_amount);fee.discount_pct=request.POST.get('discount_pct',0) or 0
        fee.effective_date=request.POST.get('effective_date',fee.effective_date);fee.notes=request.POST.get('notes','');fee.is_active=request.POST.get('is_active')=='on';fee.save()
        messages.success(request,'Fee updated!');return redirect('fee_structure')

@admin_required
@require_POST
def fee_structure_delete(request,pk):
    fee=get_object_or_404(FeeStructures,pk=pk);fee.delete();messages.success(request,'Deleted.');return redirect('fee_structure')

@admin_required
@require_POST
def fee_structure_toggle(request,pk):
    fee=get_object_or_404(FeeStructures,pk=pk);fee.is_active=not fee.is_active;fee.save()
    return JsonResponse({'status':'ok','is_active':fee.is_active,'message':f'Fee {"Active" if fee.is_active else "Inactive"}.'})

@admin_required
def duration_master(request):
       
    if request.method == 'POST':
        duration_name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        is_active   = request.POST.get('is_active') == 'on'

        if not duration_name:
            messages.error(request, 'Duration name is required.')
        elif Duration.objects.filter(duration_name__iexact=duration_name).exists():
            messages.error(request, f'"{duration_name}" already exists. Please use a different name.')
        else:
            Duration.objects.create(
                duration_name=duration_name,
                description=description,
                is_active=is_active,
            )
            messages.success(request, f'"{duration_name}" has been added successfully!')
            return redirect('duration_master')

    durations = Duration.objects.all()
    total       = durations.count()
    active_count = durations.filter(is_active=True).count()
    inactive_count = durations.filter(is_active=False).count()
    
    return render(request, 'masters/duration_master.html', {
        'durations':       durations,
        'total':        total,
        'active_count': active_count,
        'inactive_count': inactive_count
        # 'user': request.current_user,
    })

def duration_edit(request, pk):
   
    duration = get_object_or_404(Duration, pk=pk)

    if request.method == 'GET':
        return JsonResponse({
            'id':          duration.pk,
            'name':        duration.duration_name,
            'description': duration.description,
            'is_active':   duration.is_active,
        })

    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        is_active   = request.POST.get('is_active') == 'on'

        if not name:
            messages.error(request, 'Duration name is required.')
            return redirect('duration_master')

        if Duration.objects.filter(duration_name__iexact=name).exclude(pk=pk).exists():
            messages.error(request, f'"{name}" already exists.')
            return redirect('duration_master')

        duration.duration_name        = name
        duration.description = description
        duration.is_active   = is_active
        duration.save()

        messages.success(request, f'"{name}" has been updated successfully!')
        return redirect('duration_master')


@require_POST
def duration_delete(request, pk):
   
    duration = get_object_or_404(Duration, pk=pk)
    name  = duration.duration_name
    duration.delete()
    messages.success(request, f'"{name}" has been deleted.')
    return redirect('duration_master')


@require_POST
def duration_toggle_status(request, pk):
   
    duration = get_object_or_404(Duration, pk=pk)
    duration.is_active = not duration.is_active
    duration.save()
    return JsonResponse({
        'status':    'ok',
        'is_active': duration.is_active,
        'message':   f'"{duration.duration_name}" marked as {"Active" if duration.is_active else "Inactive"}.',
    })

@login_required
@permission_required('notifications')
@require_POST
def notify_all(request):
    """
    AJAX POST endpoint.
    Body: { "scope": "today" | "week" | "month" | "all" }
    Returns JSON list of students with their WhatsApp numbers & pre-built messages.
    Also logs each notification to ActivityLog.
    """
    try:
        body  = _json.loads(request.body)
        scope = body.get('scope', 'all')
    except Exception:
        scope = 'all'

    today     = date.today()
    week_end  = today + timedelta(days=7)
    month_end = today + timedelta(days=30)

    qs = StudentData.objects.filter(status='active').select_related('sport', 'batch', 'duration')

    if scope == 'today':
        qs = qs.filter(subscription_expiry=today)
    elif scope == 'week':
        qs = qs.filter(subscription_expiry__gte=today, subscription_expiry__lte=week_end)
    elif scope == 'month':
        qs = qs.filter(subscription_expiry__gte=today, subscription_expiry__lte=month_end)
    else:  # 'all' — everyone expiring within 30 days
        qs = qs.filter(subscription_expiry__gte=today, subscription_expiry__lte=month_end)

    results = []
    logged  = 0

    for s in qs:
        # Clean phone — digits only, add 91 prefix if Indian number without country code
        raw_phone = s.parent_whatsapp.strip()
        clean     = ''.join(filter(str.isdigit, raw_phone))
        if len(clean) == 10:
            clean = '91' + clean          # add India country code
        elif clean.startswith('0'):
            clean = '91' + clean[1:]

        days_left = (s.subscription_expiry - today).days

        if days_left == 0:
            urgency = "⚠️ *EXPIRES TODAY*"
        elif days_left <= 3:
            urgency = f"⚠️ Expires in *{days_left} day{'s' if days_left > 1 else ''}*"
        else:
            urgency = f"📅 Expires on *{s.subscription_expiry.strftime('%d %b %Y')}*"

        message = (
            f"Hello *{s.parent_name}*! 🏅\n\n"
            f"This is a reminder from *Sports Academy*.\n\n"
            f"Your child *{s.full_name}*'s *{s.sport.name}* subscription is expiring soon.\n"
            f"{urgency}\n\n"
            f"📋 Details:\n"
            f"• Student ID: {s.student_id}\n"
            f"• Sport: {s.sport.name}\n"
            f"• Batch: {s.batch.name}\n"
            f"• Duration: {s.duration.duration_name}\n"
            f"• Expiry: {s.subscription_expiry.strftime('%d %b %Y')}\n\n"
            f"Please renew at the earliest to continue uninterrupted training. "
            f"Contact us or visit the academy to renew.\n\n"
            f"Thank you! 🙏"
        )

        results.append({
            'student_id':   s.student_id,
            'name':         s.full_name,
            'parent_name':  s.parent_name,
            'phone':        clean,
            'raw_phone':    raw_phone,
            'sport':        s.sport.name,
            'expiry':       s.subscription_expiry.strftime('%d %b %Y'),
            'days_left':    days_left,
            'message':      message,
        })

        # Log to ActivityLog
        _log(
            'expiry_alert',
            f'WhatsApp reminder queued for {s.full_name}',
            f'Parent: {s.parent_name} · {raw_phone} · Expires: {s.subscription_expiry}',
            student=s,
        )
        logged += 1

    return JsonResponse({
        'success': True,
        'count':   len(results),
        'scope':   scope,
        'students': results,
        'message': f'{logged} reminder{"s" if logged != 1 else ""} prepared.',
    })


@login_required
@permission_required('attendance')
def coach_attendance_history_export(request):
    """
    Downloads coach attendance for the selected month + coach filter as CSV.
    Accepts same GET params as coach_attendance_history:
      ?year=YYYY&month=M&coach=<pk>
    """
    today = date.today()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))

    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    _, days_in_month = monthrange(year, month)
    sel_coach_id = request.GET.get('coach', '')
    month_label  = date(year, month, 1).strftime('%B_%Y')

    coaches = Coach.objects.filter(status='active').prefetch_related('sports_coached')

    att_qs = CoachAttendance.objects.filter(
        date__year=year, date__month=month
    ).select_related('coach', 'marked_by')
    if sel_coach_id:
        att_qs = att_qs.filter(coach_id=sel_coach_id)

    # Build lookup {coach_pk: {day_int: record}}
    raw = {}
    for a in att_qs:
        raw.setdefault(a.coach_id, {})[a.date.day] = a

    STATUS_LABEL = {'present': 'Present', 'absent': 'Absent',
                    'late': 'Late', 'on_leave': 'On Leave'}

    # Build filename
    coach_suffix = f'_Coach{sel_coach_id}' if sel_coach_id else '_AllCoaches'
    filename = f'Coach_Attendance_{month_label}{coach_suffix}.csv'

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Header row: Coach | Coach ID | Day 1 ... Day N | Present | Absent | Late | On Leave | Attendance %
    day_headers = [str(d) for d in range(1, days_in_month + 1)]
    writer.writerow(
        ['Coach Name', 'Coach ID'] +
        day_headers +
        ['Present', 'Absent', 'Late', 'On Leave', 'Attendance %']
    )

    for c in coaches:
        if sel_coach_id and str(c.pk) != sel_coach_id:
            continue

        day_map = raw.get(c.pk, {})
        row_cells = []
        for d in range(1, days_in_month + 1):
            rec = day_map.get(d)
            is_future = date(year, month, d) > today
            if is_future:
                row_cells.append('')
            elif rec:
                row_cells.append(STATUS_LABEL.get(rec.status, rec.status))
            else:
                row_cells.append('-')

        present  = sum(1 for r in day_map.values() if r.status == 'present')
        absent   = sum(1 for r in day_map.values() if r.status == 'absent')
        late     = sum(1 for r in day_map.values() if r.status == 'late')
        on_leave = sum(1 for r in day_map.values() if r.status == 'on_leave')
        pct      = round(present / days_in_month * 100) if days_in_month else 0

        writer.writerow(
            [c.full_name, c.coach_id] +
            row_cells +
            [present, absent, late, on_leave, f'{pct}%']
        )

    return response


@login_required
@permission_required('attendance')
def student_attendance_history_export(request):
    """
    Downloads student attendance for the selected month + filters as CSV.
    Accepts same GET params as student_attendance_history:
      ?year=YYYY&month=M&sport=<pk>&batch=<pk>&student=<pk>
    """
    today = date.today()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))

    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    _, days_in_month = monthrange(year, month)
    sel_sport   = request.GET.get('sport', '')
    sel_batch   = request.GET.get('batch', '')
    sel_student = request.GET.get('student', '')
    month_label = date(year, month, 1).strftime('%B_%Y')

    student_qs = StudentData.objects.filter(status='active').select_related(
        'sport', 'batch', 'expertise_level'
    )
    if request.current_user.is_coach and request.current_user.coach:
        student_qs = student_qs.filter(assigned_coach=request.current_user.coach)
    if sel_sport:   student_qs = student_qs.filter(sport_id=sel_sport)
    if sel_batch:   student_qs = student_qs.filter(batch_id=sel_batch)
    if sel_student: student_qs = student_qs.filter(pk=sel_student)

    att_qs = StudentAttendance.objects.filter(
        date__year=year, date__month=month,
        student__in=student_qs
    ).select_related('student')

    raw = {}
    for a in att_qs:
        raw.setdefault(a.student_id, {})[a.date.day] = a

    STATUS_LABEL = {'present': 'Present', 'absent': 'Absent',
                    'late': 'Late', 'excused': 'Excused'}

    # Build filename with applied filters baked in
    parts = [f'Student_Attendance_{month_label}']
    if sel_sport:
        try:
            parts.append(f'Sport{sel_sport}')
        except Exception:
            pass
    if sel_batch:
        parts.append(f'Batch{sel_batch}')
    if sel_student:
        parts.append(f'Student{sel_student}')
    filename = '_'.join(parts) + '.csv'

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Header row
    day_headers = [str(d) for d in range(1, days_in_month + 1)]
    writer.writerow(
        ['Student Name', 'Student ID', 'Sport', 'Batch', 'Expertise Level'] +
        day_headers +
        ['Present', 'Absent', 'Late', 'Excused', 'Attendance %']
    )

    for s in student_qs:
        day_map = raw.get(s.pk, {})
        row_cells = []
        for d in range(1, days_in_month + 1):
            rec = day_map.get(d)
            is_future = date(year, month, d) > today
            if is_future:
                row_cells.append('')
            elif rec:
                row_cells.append(STATUS_LABEL.get(rec.status, rec.status))
            else:
                row_cells.append('-')

        present = sum(1 for r in day_map.values() if r.status == 'present')
        absent  = sum(1 for r in day_map.values() if r.status == 'absent')
        late    = sum(1 for r in day_map.values() if r.status == 'late')
        excused = sum(1 for r in day_map.values() if r.status == 'excused')
        pct     = round(present / days_in_month * 100) if days_in_month else 0

        writer.writerow(
            [s.full_name, s.student_id, s.sport.name, s.batch.name,
             s.expertise_level.name] +
            row_cells +
            [present, absent, late, excused, f'{pct}%']
        )

    return response


@login_required
@permission_required('Payments')
def student_payment_history(request):
 
    # ── Auto-sync expired status ──────────────────────────────
    today = timezone.now().date()
    StudentData.objects.filter(
        status='active',
        subscription_expiry__lt=today
    ).update(status='expired')
    # ─────────────────────────────────────────────────────────
 
    qs = StudentData.objects.select_related(
        'sport', 'batch', 'expertise_level', 'duration',
        'fee_structure', 'assigned_coach',
    ).order_by('-created_at')
 
    # ── Filter params ─────────────────────────────────────────
    sel_sport      = request.GET.get('sport', '')
    sel_batch      = request.GET.get('batch', '')
    sel_expertise  = request.GET.get('expertise', '')
    sel_coach      = request.GET.get('coach', '')
    sel_pay_status = request.GET.get('pay_status', '')
    sel_status     = request.GET.get('status', '')
    sel_expiry     = request.GET.get('expiry_within', '')
    sel_due_min    = request.GET.get('due_min', '')
 
    if sel_sport:
        qs = qs.filter(sport_id=_int_or_none(sel_sport))
    if sel_batch:
        qs = qs.filter(batch_id=_int_or_none(sel_batch))
    if sel_expertise:
        qs = qs.filter(expertise_level_id=_int_or_none(sel_expertise))
    if sel_coach:
        qs = qs.filter(assigned_coach_id=_int_or_none(sel_coach))
    if sel_status:
        qs = qs.filter(status=sel_status)
 
    if sel_expiry:
        days = _int_or_none(sel_expiry)
        if days == 0:
            qs = qs.filter(subscription_expiry__lt=today)
        elif days is not None:
            qs = qs.filter(
                subscription_expiry__gte=today,
                subscription_expiry__lte=today + timedelta(days=days),
            )
 
    if sel_due_min:
        try:
            qs = qs.filter(fee_due__gte=Decimal(sel_due_min))
        except InvalidOperation:
            pass
 
    # ── In-Python pay_status filter ───────────────────────────
    students = list(qs)
    if sel_pay_status == 'paid':
        students = [s for s in students if s.fee_due == 0 and s.total_fee > 0]
    elif sel_pay_status == 'partial':
        students = [s for s in students if 0 < s.fee_paid < s.total_fee]
    elif sel_pay_status == 'unpaid':
        students = [s for s in students if s.fee_paid == 0]
    elif sel_pay_status == 'has_due':
        students = [s for s in students if s.fee_due > 0]
 
    # ── Fee aggregates ────────────────────────────────────────
    # StudentData.total_fee is overwritten on every renewal cycle, so summing
    # it only reflects the CURRENT cycle per student — useless for lifetime totals.
    #
    # Instead we derive the three headline figures from two authoritative sources:
    #
    #   total_paid — sum of every Payment row for filtered students.
    #                Payment records are never deleted or reset; they are the
    #                single source of truth for money actually collected.
    #
    #   total_due  — sum of StudentData.fee_due for filtered students.
    #                This field is maintained by Payment.save() and the renewal
    #                carry-forward logic, so it always reflects live outstanding
    #                balance including any dues rolled over from previous cycles.
    #
    #   total_fee  — derived as total_paid + total_due.
    #                This equals everything ever billed across all cycles:
    #                  admission cycle(s) collected  → in Payment rows
    #                  renewal cycle(s) collected    → in Payment rows
    #                  anything still unpaid         → in fee_due
    #                No separate storage needed; the equation always holds.
 
    # Step 1: lifetime collected — sum all Payment rows for the filtered students
    student_pks = qs.values_list('pk', flat=True)
    total_paid = Payment.objects.filter(
        student_id__in=student_pks
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
 
    # Step 2: current outstanding — sum fee_due on StudentData
    # Exclude students with total_fee=0 (no fee structure assigned yet) to avoid
    # distorting collection_pct with zero-fee admissions.
    fee_qs   = qs.filter(total_fee__gt=0)
    total_due = fee_qs.aggregate(
        t=Sum('fee_due')
    )['t'] or Decimal('0')
 
    # Step 3: lifetime total fees = everything ever paid + everything still owed
    total_fee = total_paid + total_due
 
    collection_pct  = (
        round(float(total_paid) / float(total_fee) * 100)
        if total_fee > 0 else 0
    )
    outstanding_pct = 100 - collection_pct
 
    # ── Status counts ─────────────────────────────────────────
    total_students     = qs.count()
    active_students    = qs.filter(status='active').count()
    expired_students   = qs.filter(status='expired').count()
    suspended_students = qs.filter(status='suspended').count()
    due_students_count = qs.filter(fee_due__gt=0).count()
 
    # ── Filter dropdowns ──────────────────────────────────────
    sports  = Sport.objects.filter(is_active=True)
    batches = Batch.objects.filter(is_active=True)
    levels  = ExpertiseLevel.objects.filter(is_active=True)
    coaches = Coach.objects.filter(is_active=True)
 
    # ── Active filter count ───────────────────────────────────
    filter_flags = [
        sel_sport, sel_batch, sel_expertise, sel_coach,
        sel_pay_status, sel_status, sel_expiry, sel_due_min,
    ]
    active_filter_count = sum(1 for f in filter_flags if f)
 
    # ── Friendly filter chip names ────────────────────────────
    sel_sport_name     = Sport.objects.filter(pk=_int_or_none(sel_sport)).values_list('name', flat=True).first() or ''
    sel_batch_name     = Batch.objects.filter(pk=_int_or_none(sel_batch)).values_list('name', flat=True).first() or ''
    sel_expertise_name = ExpertiseLevel.objects.filter(pk=_int_or_none(sel_expertise)).values_list('name', flat=True).first() or ''
    coach_obj          = Coach.objects.filter(pk=_int_or_none(sel_coach)).first()
    sel_coach_name     = coach_obj.full_name if coach_obj else ''
 
    month_revenue = Payment.objects.filter(
        payment_date__year=today.year,
        payment_date__month=today.month,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
 
    ctx = {
        'students':            students,
        # 'total_students':      total_students,
        'active_students':     active_students,
        'expired_students':    expired_students,
        'suspended_students':  suspended_students,
        'total_fee':           total_fee,
        'total_paid':          total_paid,
        'total_due':           total_due,
        'collection_pct':      collection_pct,
        'outstanding_pct':     outstanding_pct,
        'due_students_count':  due_students_count,
        'month_revenue':       month_revenue,
        'sports':              sports,
        'batches':             batches,
        'levels':              levels,
        'coaches':             coaches,
        'sel_sport':           sel_sport,
        'sel_batch':           sel_batch,
        'sel_expertise':       sel_expertise,
        'sel_coach':           sel_coach,
        'sel_pay_status':      sel_pay_status,
        'sel_status':          sel_status,
        'sel_expiry':          sel_expiry,
        'sel_due_min':         sel_due_min,
        'sel_sport_name':      sel_sport_name,
        'sel_batch_name':      sel_batch_name,
        'sel_expertise_name':  sel_expertise_name,
        'sel_coach_name':      sel_coach_name,
        'active_filter_count': active_filter_count,
        'today':               today,
    }
    return render(request, 'fees/payment_records_updated.html', ctx)
 
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  2.  RECORD PAYMENT  (POST /payments/record/)
# ══════════════════════════════════════════════════════════════════════════════
 
@login_required
@require_POST
def record_payment(request):
    """
    JSON endpoint.  Body:
        {
            "student_pk":   <int>,
            "amount":       <number>,
            "payment_mode": "cash" | "upi" | "online" | "cheque" | "other",
            "payment_date": "YYYY-MM-DD",
            "reference":    "<str>",   // optional
            "note":         "<str>"    // optional
        }
 
    Response (success):
        {
            "success": true,
            "fee_paid": <float>,
            "fee_due":  <float>,
            "total_fee": <float>
        }
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
 
    student_pk   = data.get('student_pk')
    amount_raw   = data.get('amount')
    payment_mode = data.get('payment_mode', '').strip()
    payment_date = data.get('payment_date', '').strip()
    reference    = data.get('reference', '').strip()
    note         = data.get('note', '').strip()
 
    # ── basic validation ───────────────────────────────────────
    if not all([student_pk, amount_raw, payment_mode, payment_date]):
        return JsonResponse(
            {'success': False, 'error': 'student_pk, amount, payment_mode and payment_date are required.'},
            status=400,
        )
 
    try:
        amount = Decimal(str(amount_raw)).quantize(Decimal('0.01'))
    except InvalidOperation:
        return JsonResponse({'success': False, 'error': 'Invalid amount.'}, status=400)
 
    if amount <= 0:
        return JsonResponse({'success': False, 'error': 'Amount must be greater than zero.'}, status=400)
 
    valid_modes = [m[0] for m in Payment.MODE_CHOICES]
    if payment_mode not in valid_modes:
        return JsonResponse({'success': False, 'error': f'Invalid payment_mode. Choose from {valid_modes}.'}, status=400)
 
    # ── parse date ─────────────────────────────────────────────
    from datetime import date as date_type
    try:
        year, month, day = payment_date.split('-')
        pay_date = date_type(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return JsonResponse({'success': False, 'error': 'Invalid payment_date. Use YYYY-MM-DD.'}, status=400)
 
    # ── fetch student ──────────────────────────────────────────
    student = get_object_or_404(StudentData, pk=student_pk)
 
    if amount > student.fee_due:
        return JsonResponse(
            {'success': False,
             'error': f'Amount ₹{amount} exceeds outstanding due ₹{student.fee_due}.'},
            status=400,
        )
 
    # ── resolve SystemUser for recorded_by ────────────────────
    # If you use Django's auth + a separate SystemUser, adjust accordingly.
    # Here we try to find the matching SystemUser by username.
    recorded_by = None
    if request.user.is_authenticated:
        from .models import SystemUser
        recorded_by = SystemUser.objects.filter(username=request.user.username).first()
 
    # ── atomic update ──────────────────────────────────────────
    with transaction.atomic():
        Payment.objects.create(
            student      = student,
            amount       = amount,
            payment_mode = payment_mode,
            payment_date = pay_date,
            reference    = reference,
            note         = note,
            recorded_by  = recorded_by,
        )
 
        # Update student fee fields
        student.fee_paid += amount
        student.fee_due  -= amount
        # Guard against floating-point drift going below zero
        if student.fee_due < 0:
            student.fee_due = Decimal('0')
        student.save(update_fields=['fee_paid', 'fee_due', 'updated_at'])
 
        # Activity log
        ActivityLog.objects.create(
            activity_type='payment',
            title=f'Payment of ₹{amount} received from {student.full_name}',
            description=(
                f'Mode: {payment_mode} | Date: {pay_date}'
                + (f' | Ref: {reference}' if reference else '')
                + (f' | Note: {note}' if note else '')
            ),
            student=student,
        )
 
    return JsonResponse({
        'success':   True,
        'fee_paid':  float(student.fee_paid),
        'fee_due':   float(student.fee_due),
        'total_fee': float(student.total_fee),
    })
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  3.  PAYMENT HISTORY  (GET /payments/history/<pk>/)
# ══════════════════════════════════════════════════════════════════════════════
 
@login_required
@permission_required('payment')
def payment_history(request, pk):
    """
    AJAX endpoint — returns JSON list of all Payment records for one student.
    Response:
        {
            "payments": [
                {
                    "id":           <int>,
                    "amount":       "1500.00",
                    "mode":         "cash",
                    "mode_display": "Cash",
                    "date":         "12 Jan 2025",
                    "reference":    "...",
                    "note":         "...",
                    "recorded_by":  "admin"
                },
                ...
            ]
        }
    """
    student  = get_object_or_404(StudentData, pk=pk)
    payments = (
        Payment.objects
        .filter(student=student)
        .select_related('recorded_by')
        .order_by('-payment_date', '-created_at')
    )
 
    data = [
        {
            'id':           p.pk,
            'amount':       str(p.amount),
            'mode':         p.payment_mode,
            'mode_display': p.mode_display,
            'date':         p.payment_date.strftime('%d %b %Y'),
            'reference':    p.reference,
            'note':         p.note,
            'recorded_by':  p.recorded_by.username if p.recorded_by else '',
        }
        for p in payments
    ]
 
    return JsonResponse({'payments': data})
 
@login_required
@permission_required('attendance')
def attendance_dashboard(request):
    """
    Aggregates student & coach attendance data for the dashboard.
    All heavy lifting is done in Python / Django ORM so the template
    receives clean dicts / lists that Chart.js can consume directly.
    """
    today      = date.today()
    cur_year   = today.year
    cur_month  = today.month

    # ── 1. SUMMARY CARDS ──────────────────────────────────────────────

    # Current month date range
    _, days_in_cur_month = monthrange(cur_year, cur_month)
    month_start = date(cur_year, cur_month, 1)
    month_end   = date(cur_year, cur_month, days_in_cur_month)

    # Student cards
    student_total_marked = StudentAttendance.objects.filter(
        date__year=cur_year, date__month=cur_month
    ).count()
    student_present_today = StudentAttendance.objects.filter(
        date=today, status='present'
    ).count()
    student_absent_today  = StudentAttendance.objects.filter(
        date=today, status='absent'
    ).count()
    student_late_today    = StudentAttendance.objects.filter(
        date=today, status='late'
    ).count()
    student_present_month = StudentAttendance.objects.filter(
        date__year=cur_year, date__month=cur_month, status='present'
    ).count()
    student_absent_month  = StudentAttendance.objects.filter(
        date__year=cur_year, date__month=cur_month, status='absent'
    ).count()

    # Coach cards
    coach_present_today = CoachAttendance.objects.filter(
        date=today, status='present'
    ).count()
    coach_absent_today  = CoachAttendance.objects.filter(
        date=today, status='absent'
    ).count()
    coach_on_leave_today = CoachAttendance.objects.filter(
        date=today, status='on_leave'
    ).count()
    coach_present_month = CoachAttendance.objects.filter(
        date__year=cur_year, date__month=cur_month, status='present'
    ).count()
    coach_absent_month  = CoachAttendance.objects.filter(
        date__year=cur_year, date__month=cur_month, status='absent'
    ).count()

    total_active_students = StudentData.objects.filter(status='active').count()
    total_active_coaches  = Coach.objects.filter(status='active').count()

    # ── 2. MONTH-WISE STUDENT ATTENDANCE (last 6 months) ─────────────

    months_6 = []
    for i in range(5, -1, -1):
        # subtract i months from today
        m = cur_month - i
        y = cur_year
        while m <= 0:
            m += 12
            y -= 1
        months_6.append((y, m))

    student_monthly_labels   = []
    student_monthly_present  = []
    student_monthly_absent   = []
    student_monthly_late     = []
    student_monthly_excused  = []

    for y, m in months_6:
        label = date(y, m, 1).strftime('%b %Y')
        student_monthly_labels.append(label)
        qs = StudentAttendance.objects.filter(date__year=y, date__month=m)
        student_monthly_present.append(qs.filter(status='present').count())
        student_monthly_absent.append(qs.filter(status='absent').count())
        student_monthly_late.append(qs.filter(status='late').count())
        student_monthly_excused.append(qs.filter(status='excused').count())

    # ── 3. CURRENT MONTH — STUDENT DAY-WISE ──────────────────────────

    day_labels        = [str(d) for d in range(1, days_in_cur_month + 1)]
    day_student_pres  = []
    day_student_abs   = []

    att_by_day_student = defaultdict(lambda: {'present': 0, 'absent': 0})
    for a in StudentAttendance.objects.filter(date__year=cur_year, date__month=cur_month):
        att_by_day_student[a.date.day][a.status] = (
            att_by_day_student[a.date.day].get(a.status, 0) + 1
        )
    for d in range(1, days_in_cur_month + 1):
        day_student_pres.append(att_by_day_student[d].get('present', 0))
        day_student_abs.append(att_by_day_student[d].get('absent', 0))

    # ── 4. MONTH-WISE COACH ATTENDANCE (last 6 months) ───────────────

    coach_monthly_labels   = []
    coach_monthly_present  = []
    coach_monthly_absent   = []
    coach_monthly_late     = []
    coach_monthly_on_leave = []

    for y, m in months_6:
        label = date(y, m, 1).strftime('%b %Y')
        coach_monthly_labels.append(label)
        qs = CoachAttendance.objects.filter(date__year=y, date__month=m)
        coach_monthly_present.append(qs.filter(status='present').count())
        coach_monthly_absent.append(qs.filter(status='absent').count())
        coach_monthly_late.append(qs.filter(status='late').count())
        coach_monthly_on_leave.append(qs.filter(status='on_leave').count())

    # ── 5. CURRENT MONTH — COACH DAY-WISE ───────────────────────────

    day_coach_pres  = []
    day_coach_abs   = []
    att_by_day_coach = defaultdict(lambda: {'present': 0, 'absent': 0})
    for a in CoachAttendance.objects.filter(date__year=cur_year, date__month=cur_month):
        att_by_day_coach[a.date.day][a.status] = (
            att_by_day_coach[a.date.day].get(a.status, 0) + 1
        )
    for d in range(1, days_in_cur_month + 1):
        day_coach_pres.append(att_by_day_coach[d].get('present', 0))
        day_coach_abs.append(att_by_day_coach[d].get('absent', 0))

    # ── 6. COACH-WISE STUDENT PRESENCE (current month) ───────────────

    coaches_active = Coach.objects.filter(status='active').prefetch_related('students')
    coach_wise_labels  = []
    coach_wise_present = []
    coach_wise_absent  = []

    for coach in coaches_active:
        student_ids = list(
            StudentData.objects.filter(assigned_coach=coach, status='active')
            .values_list('pk', flat=True)
        )
        if not student_ids:
            continue
        qs = StudentAttendance.objects.filter(
            date__year=cur_year, date__month=cur_month,
            student_id__in=student_ids
        )
        p = qs.filter(status='present').count()
        a = qs.filter(status='absent').count()
        coach_wise_labels.append(coach.full_name)
        coach_wise_present.append(p)
        coach_wise_absent.append(a)

    # ── 7. SPORT-WISE STUDENT ATTENDANCE (current month) ─────────────

    from django.db.models import Count as DjCount
    sport_att = (
        StudentAttendance.objects
        .filter(date__year=cur_year, date__month=cur_month)
        .values('student__sport__name', 'status')
        .annotate(cnt=DjCount('id'))
    )
    sport_att_map = defaultdict(lambda: {'present': 0, 'absent': 0, 'late': 0})
    for row in sport_att:
        sport_name = row['student__sport__name'] or 'Unknown'
        sport_att_map[sport_name][row['status']] = row['cnt']

    sport_att_labels   = list(sport_att_map.keys())
    sport_att_present  = [sport_att_map[s]['present']  for s in sport_att_labels]
    sport_att_absent   = [sport_att_map[s]['absent']   for s in sport_att_labels]
    sport_att_late     = [sport_att_map[s]['late']     for s in sport_att_labels]

    # ── 8. ATTENDANCE RATE — PER COACH (current month) ───────────────

    coach_rate_labels = []
    coach_rate_pct    = []
    total_days = days_in_cur_month
    for coach in coaches_active:
        qs = CoachAttendance.objects.filter(
            coach=coach, date__year=cur_year, date__month=cur_month
        )
        p = qs.filter(status='present').count()
        pct = round(p / total_days * 100) if total_days else 0
        coach_rate_labels.append(coach.full_name)
        coach_rate_pct.append(pct)

    # ── 9. WEEKLY HEATMAP DATA — current month students ──────────────
    # Mon-Sun × weeks: just pass raw counts per weekday (0=Mon)

    weekday_labels  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    weekday_present = [0] * 7
    weekday_absent  = [0] * 7
    for a in StudentAttendance.objects.filter(date__year=cur_year, date__month=cur_month):
        wd = a.date.weekday()
        if a.status == 'present':
            weekday_present[wd] += 1
        elif a.status == 'absent':
            weekday_absent[wd] += 1

    import json as _json

    ctx = {
        'user': request.current_user,
        'today': today,
        'cur_month_name': today.strftime('%B %Y'),
        'days_in_cur_month': days_in_cur_month,

        # Summary card data
        'total_active_students': total_active_students,
        'total_active_coaches':  total_active_coaches,
        'student_present_today': student_present_today,
        'student_absent_today':  student_absent_today,
        'student_late_today':    student_late_today,
        'student_present_month': student_present_month,
        'student_absent_month':  student_absent_month,
        'coach_present_today':   coach_present_today,
        'coach_absent_today':    coach_absent_today,
        'coach_on_leave_today':  coach_on_leave_today,
        'coach_present_month':   coach_present_month,
        'coach_absent_month':    coach_absent_month,

        # Chart data as JSON
        'student_monthly_labels':  _json.dumps(student_monthly_labels),
        'student_monthly_present': _json.dumps(student_monthly_present),
        'student_monthly_absent':  _json.dumps(student_monthly_absent),
        'student_monthly_late':    _json.dumps(student_monthly_late),
        'student_monthly_excused': _json.dumps(student_monthly_excused),

        'day_labels':        _json.dumps(day_labels),
        'day_student_pres':  _json.dumps(day_student_pres),
        'day_student_abs':   _json.dumps(day_student_abs),

        'coach_monthly_labels':   _json.dumps(coach_monthly_labels),
        'coach_monthly_present':  _json.dumps(coach_monthly_present),
        'coach_monthly_absent':   _json.dumps(coach_monthly_absent),
        'coach_monthly_late':     _json.dumps(coach_monthly_late),
        'coach_monthly_on_leave': _json.dumps(coach_monthly_on_leave),

        'day_coach_pres': _json.dumps(day_coach_pres),
        'day_coach_abs':  _json.dumps(day_coach_abs),

        'coach_wise_labels':  _json.dumps(coach_wise_labels),
        'coach_wise_present': _json.dumps(coach_wise_present),
        'coach_wise_absent':  _json.dumps(coach_wise_absent),

        'sport_att_labels':  _json.dumps(sport_att_labels),
        'sport_att_present': _json.dumps(sport_att_present),
        'sport_att_absent':  _json.dumps(sport_att_absent),
        'sport_att_late':    _json.dumps(sport_att_late),

        'coach_rate_labels': _json.dumps(coach_rate_labels),
        'coach_rate_pct':    _json.dumps(coach_rate_pct),

        'weekday_labels':  _json.dumps(weekday_labels),
        'weekday_present': _json.dumps(weekday_present),
        'weekday_absent':  _json.dumps(weekday_absent),
    }

    return render(request, 'attendance/attendance_dashboard.html', ctx)

@login_required
@permission_required('student_admission')
def student_renew(request, pk):
    student = get_object_or_404(
        StudentData.objects.select_related(
            'sport', 'batch', 'expertise_level', 'duration', 'fee_structure'
        ),
        pk=pk
    )
 
    if request.method == 'POST':
        batch_id       = request.POST.get('batch')
        level_id       = request.POST.get('expertise_level')
        duration_id    = request.POST.get('duration')
        fee_id         = request.POST.get('fee_id', '')
        fee_paid_new   = float(request.POST.get('fee_paid', '0') or '0')
        start_date_str = request.POST.get('start_date', str(date.today()))
        coach_id       = request.POST.get('assigned_coach', '')
        new_status     = request.POST.get('status', student.status)
        payment_mode   = request.POST.get('payment_mode', 'cash')
        reference      = request.POST.get('reference', '').strip()
 
        if not all([batch_id, level_id, duration_id]):
            messages.error(request, 'Batch, level and duration are required.')
        else:
            # ── Duration → expiry ─────────────────────────────────────────
            try:
                dur_obj = Duration.objects.get(pk=duration_id)
                months  = int(dur_obj.duration_name.split()[0])
                start   = date.fromisoformat(start_date_str)
                expiry  = start + relativedelta(months=months)
            except Exception:
                start   = date.today()
                expiry  = start + timedelta(days=30)
                dur_obj = None
 
            # ── Fee lookup ────────────────────────────────────────────────
            fee_obj         = None
            new_cycle_fee   = Decimal('0')   # fee for THIS renewal cycle only
 
            if fee_id:
                try:
                    fee_obj       = FeeStructures.objects.get(pk=fee_id)
                    new_cycle_fee = Decimal(str(fee_obj.discounted_amount))
                except FeeStructures.DoesNotExist:
                    pass
 
            # Fallback: use student's existing fee structure
            if not fee_obj and student.fee_structure:
                fee_obj       = student.fee_structure
                new_cycle_fee = Decimal(str(fee_obj.discounted_amount))
 
            # ── Carry forward any unpaid due from previous cycle ──────────
            # Re-fetch fee_due directly from DB to get the exact current value,
            # avoiding any stale in-memory state on the student object.
            prior_due = StudentData.objects.filter(pk=student.pk).values_list(
                'fee_due', flat=True
            ).first() or Decimal('0')
 
            # grand_total is what the student now owes in full:
            # new cycle fee + whatever they still owed before
            grand_total_fee  = new_cycle_fee + prior_due
            fee_paid_decimal = Decimal(str(fee_paid_new))
            fee_due          = max(grand_total_fee - fee_paid_decimal, Decimal('0'))
 
            # ── Coach ─────────────────────────────────────────────────────
            assigned_coach = student.assigned_coach
            if coach_id:
                try:
                    assigned_coach = Coach.objects.get(pk=coach_id)
                except Coach.DoesNotExist:
                    pass
 
            with transaction.atomic():
                # ── Step 1: Update StudentData for new cycle ──────────────
                # total_fee  = new cycle fee + carried-forward prior due
                # fee_paid   = reset to 0 — Payment.save() will increment it
                # fee_due    = grand_total — Payment.save() will decrement it
                #
                # We do NOT carry forward fee_paid from the old cycle because
                # Payment records are the source of truth for lifetime collected.
                # StudentData.fee_paid only reflects the CURRENT cycle payments.
                StudentData.objects.filter(pk=student.pk).update(
                    batch_id=batch_id,
                    expertise_level_id=level_id,
                    duration_id=duration_id,
                    fee_structure=fee_obj,
                    assigned_coach=assigned_coach,
                    subscription_start=start,
                    subscription_expiry=expiry,
                    total_fee=grand_total_fee,   # new cycle + carried-forward due
                    fee_paid=Decimal('0'),        # reset — Payment.save() increments
                    fee_due=grand_total_fee,      # reset — Payment.save() decrements
                    status=new_status,
                    is_renewal=True,
                )
 
                # Refresh so in-memory values match DB before Payment.save() fires
                student.refresh_from_db()
 
                # ── Step 2: Payment record ────────────────────────────────
                # Payment.save() does:
                #   fee_paid = 0 + fee_paid_new          ✓
                #   fee_due  = grand_total - fee_paid_new ✓
                if fee_paid_new > 0:
                    Payment.objects.create(
                        student=student,
                        amount=fee_paid_decimal,
                        payment_mode=payment_mode,
                        payment_date=start,
                        reference=reference,
                        note=(
                            f'Renewal — {student.sport.name} | '
                            f'{dur_obj.duration_name if dur_obj else ""} | '
                            f'Expires: {expiry.strftime("%d %b %Y")}'
                            + (f' | Carried forward: ₹{prior_due}' if prior_due > 0 else '')
                        ),
                        recorded_by=request.current_user,
                    )
                # If fee_paid_new == 0 the reset above already set
                # fee_paid=0 and fee_due=grand_total_fee correctly.
 
                _log(
                    'renewal',
                    f'{student.full_name} membership renewed',
                    f'Sport: {student.sport.name} | Status: {new_status} | '
                    f'New expiry: {expiry} | '
                    f'New cycle fee: ₹{new_cycle_fee} | '
                    f'Carried forward due: ₹{prior_due} | '
                    f'Grand total: ₹{grand_total_fee} | '
                    f'Paid: ₹{fee_paid_new} | Due: ₹{fee_due}',
                    student=student,
                )
 
            messages.success(
                request,
                f'✓ {student.full_name}\'s membership renewed until '
                f'{expiry.strftime("%d %b %Y")}. '
                f'Status: {new_status.capitalize()}.'
                + (f' Carried forward due: ₹{prior_due}.' if prior_due > 0 else '')
            )
            return redirect('student_detail', pk=student.pk)
 
    # ── GET ───────────────────────────────────────────────────────────────────
    prefill_fee = None
    try:
        prefill_fee = FeeStructures.objects.get(
            sport=student.sport,
            batch=student.batch,
            expertise_level=student.expertise_level,
            duration=student.duration,
            is_active=True,
        )
    except FeeStructures.DoesNotExist:
        pass
 
    return render(request, 'students/student_renew.html', {
        'user':        request.current_user,
        'student':     student,
        'batches':     Batch.objects.filter(is_active=True),
        'levels':      ExpertiseLevel.objects.filter(is_active=True),
        'durations':   Duration.objects.filter(is_active=True),
        'coaches':     Coach.objects.filter(status='active'),
        'prefill_fee': prefill_fee,
        'today':       date.today().isoformat(),
    })