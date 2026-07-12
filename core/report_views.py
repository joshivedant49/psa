# ════════════════════════════════════════════════════════════════════
#  report_views.py  — drop this file inside your app folder
#  (same folder as views.py, models.py, urls.py)
#
#  Then in views.py add at the top:
#      from .report_views import reports_page, report_pdf, report_count
#
#  Then in urls.py add inside urlpatterns:
#      path('reports/',          views.reports_page,  name='reports'),
#      path('reports/pdf/',      views.report_pdf,    name='report_pdf'),
#      path('reports/count/',    views.report_count,  name='report_count'),
# ════════════════════════════════════════════════════════════════════

from datetime import date, timedelta
from io import BytesIO
import os

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    Sport, Batch, ExpertiseLevel, Duration, Coach,
    StudentData, FeeStructures,SystemUser,CoachPermission,Payment
)

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from functools import wraps
from django.contrib import messages

# ════════════════════════════════════════════════════════════════════
#  COLOUR PALETTE  (matches your CSS design system)
# ════════════════════════════════════════════════════════════════════

C_INK        = colors.HexColor('#1E1C1A')
C_INK_SOFT   = colors.HexColor('#4A4540')
C_INK_MUTED  = colors.HexColor('#8A8480')
C_CREAM      = colors.HexColor('#F9F7F4')
C_CREAM_DARK = colors.HexColor('#F0EDE8')
C_BORDER     = colors.HexColor('#E8E4E0')
C_BORDER_MID = colors.HexColor('#D4CFC9')
C_GREEN      = colors.HexColor('#3A7A52')
C_GREEN_PALE = colors.HexColor('#EBF4EF')
C_GOLD       = colors.HexColor('#C4973A')
C_GOLD_PALE  = colors.HexColor('#FBF5E9')
C_AMBER      = colors.HexColor('#C47A30')
C_AMBER_PALE = colors.HexColor('#FDF0E3')
C_RED        = colors.HexColor('#B84040')
C_RED_PALE   = colors.HexColor('#FAEAEA')
C_BLUE       = colors.HexColor('#2E6B9E')
C_BLUE_PALE  = colors.HexColor('#E8F1FA')
C_WHITE      = colors.white
C_BLACK      = colors.black


# ════════════════════════════════════════════════════════════════════
#  PARAGRAPH STYLES
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
    """Decorator: admin always passes; coach needs explicit permission."""
    def decorator(view_fn):
        @wraps(view_fn)
        def wrapper(request, *args, **kwargs):
            user = get_current_user(request)
            if not user:
                return redirect('login')
            if user.is_admin:
                request.current_user = user
                return view_fn(request, *args, **kwargs)
            # Check coach permission
            has_perm = CoachPermission.objects.filter(
                user=user, module=module, allowed=True
            ).exists()
            if not has_perm:
                messages.error(request, f'You do not have access to this module.')
                return redirect('home')
            request.current_user = user
            return view_fn(request, *args, **kwargs)
        return wrapper
    return decorator

def _styles():
    return {
        'title': ParagraphStyle('title',
            fontName='Helvetica-Bold', fontSize=22, textColor=C_INK,
            leading=28, spaceAfter=4),
        'subtitle': ParagraphStyle('subtitle',
            fontName='Helvetica', fontSize=11, textColor=C_INK_MUTED,
            leading=16, spaceAfter=2),
        'section_head': ParagraphStyle('section_head',
            fontName='Helvetica-Bold', fontSize=10, textColor=C_WHITE,
            leading=14, alignment=TA_LEFT),
        'cell_normal': ParagraphStyle('cell_normal',
            fontName='Helvetica', fontSize=8, textColor=C_INK,
            leading=11, wordWrap='LTR'),
        'cell_bold': ParagraphStyle('cell_bold',
            fontName='Helvetica-Bold', fontSize=8, textColor=C_INK,
            leading=11),
        'cell_muted': ParagraphStyle('cell_muted',
            fontName='Helvetica', fontSize=7.5, textColor=C_INK_MUTED,
            leading=10),
        'cell_green': ParagraphStyle('cell_green',
            fontName='Helvetica-Bold', fontSize=8, textColor=C_GREEN,
            leading=11),
        'cell_red': ParagraphStyle('cell_red',
            fontName='Helvetica-Bold', fontSize=8, textColor=C_RED,
            leading=11),
        'cell_amber': ParagraphStyle('cell_amber',
            fontName='Helvetica-Bold', fontSize=8, textColor=C_AMBER,
            leading=11),
        'cell_center': ParagraphStyle('cell_center',
            fontName='Helvetica', fontSize=8, textColor=C_INK,
            leading=11, alignment=TA_CENTER),
        'summary_label': ParagraphStyle('summary_label',
            fontName='Helvetica', fontSize=9, textColor=C_INK_MUTED,
            leading=13, spaceAfter=2),
        'summary_val': ParagraphStyle('summary_val',
            fontName='Helvetica-Bold', fontSize=14, textColor=C_INK,
            leading=18),
        'summary_val_green': ParagraphStyle('summary_val_green',
            fontName='Helvetica-Bold', fontSize=14, textColor=C_GREEN,
            leading=18),
        'summary_val_red': ParagraphStyle('summary_val_red',
            fontName='Helvetica-Bold', fontSize=14, textColor=C_RED,
            leading=18),
        'filter_label': ParagraphStyle('filter_label',
            fontName='Helvetica-Bold', fontSize=8, textColor=C_INK_MUTED,
            leading=11),
        'filter_val': ParagraphStyle('filter_val',
            fontName='Helvetica', fontSize=8.5, textColor=C_INK_SOFT,
            leading=12),
        'footer': ParagraphStyle('footer',
            fontName='Helvetica', fontSize=7.5, textColor=C_INK_MUTED,
            leading=11, alignment=TA_CENTER),
    }


# ════════════════════════════════════════════════════════════════════
#  QUERY HELPERS
# ════════════════════════════════════════════════════════════════════

def _build_queryset(params):
    """Apply all filters from GET params to StudentData queryset."""
    qs = StudentData.objects.select_related(
        'sport', 'batch', 'expertise_level', 'duration', 'assigned_coach'
    )

    sport   = params.get('sport', '')
    batch   = params.get('batch', '')
    level   = params.get('expertise_level', '')
    dur     = params.get('duration', '')
    coach   = params.get('coach', '')
    status  = params.get('status', '')
    gender  = params.get('gender', '')
    fee_st  = params.get('fee_status', '')
    d_from  = params.get('date_from', '')
    d_to    = params.get('date_to', '')
    due_min = params.get('fee_due_min', '')
    due_max = params.get('fee_due_max', '')
    expiry  = params.get('expiry_within', '')

    if sport:  qs = qs.filter(sport_id=sport)
    if batch:  qs = qs.filter(batch_id=batch)
    if level:  qs = qs.filter(expertise_level_id=level)
    if dur:    qs = qs.filter(duration_id=dur)
    if coach:  qs = qs.filter(assigned_coach_id=coach)
    if status: qs = qs.filter(status=status)
    if gender: qs = qs.filter(gender=gender)

    if d_from:
        try: qs = qs.filter(admission_date__gte=date.fromisoformat(d_from))
        except ValueError: pass
    if d_to:
        try: qs = qs.filter(admission_date__lte=date.fromisoformat(d_to))
        except ValueError: pass

    if due_min:
        try: qs = qs.filter(fee_due__gte=float(due_min))
        except ValueError: pass
    if due_max:
        try: qs = qs.filter(fee_due__lte=float(due_max))
        except ValueError: pass

    if fee_st == 'fully_paid':
        qs = qs.filter(fee_due=0, total_fee__gt=0)
    elif fee_st == 'partial':
        qs = qs.filter(fee_paid__gt=0, fee_due__gt=0)
    elif fee_st == 'unpaid':
        qs = qs.filter(fee_paid=0)
    elif fee_st == 'has_due':
        qs = qs.filter(fee_due__gt=0)

    if expiry:
        today = date.today()
        try:
            days = int(expiry)
            if days == 0:
                qs = qs.filter(subscription_expiry__lt=today)
            else:
                qs = qs.filter(subscription_expiry__gte=today,
                               subscription_expiry__lte=today + timedelta(days=days))
        except ValueError:
            pass

    return qs


def _active_filters_text(params):
    """Build a human-readable list of applied filters for the PDF header."""
    parts = []
    labels = {
        'sport':           ('Sport',         lambda v: Sport.objects.filter(pk=v).values_list('name', flat=True).first()),
        'batch':           ('Batch',         lambda v: Batch.objects.filter(pk=v).values_list('name', flat=True).first()),
        'expertise_level': ('Level',         lambda v: ExpertiseLevel.objects.filter(pk=v).values_list('name', flat=True).first()),
        'duration':        ('Duration',      lambda v: Duration.objects.filter(pk=v).values_list('duration_name', flat=True).first()),
        'coach':           ('Coach',         lambda v: Coach.objects.filter(pk=v).values_list('first_name', flat=True).first()),
        'status':          ('Status',        lambda v: v.title()),
        'gender':          ('Gender',        lambda v: {'M':'Male','F':'Female','O':'Other'}.get(v, v)),
        'fee_status':      ('Fee Status',    lambda v: {
                                'fully_paid':'Fully Paid','partial':'Partial',
                                'unpaid':'Unpaid','has_due':'Has Due'}.get(v, v)),
        'date_from':       ('Admitted From', lambda v: v),
        'date_to':         ('Admitted To',   lambda v: v),
        'fee_due_min':     ('Due ≥ ₹',       lambda v: v),
        'fee_due_max':     ('Due ≤ ₹',       lambda v: v),
        'expiry_within':   ('Expiry',        lambda v: f'Next {v} days' if v != '0' else 'Already expired'),
    }
    for key, (label, fn) in labels.items():
        val = params.get(key, '')
        if val:
            try:
                resolved = fn(val)
                if resolved:
                    parts.append(f'{label}: {resolved}')
            except Exception:
                pass
    return parts


# ════════════════════════════════════════════════════════════════════
#  PAGE HEADER / FOOTER CANVAS CALLBACK
# ════════════════════════════════════════════════════════════════════

class ReportCanvas:
    """Mixin to draw header strip and footer on every page."""

    def __init__(self, report_title, generated_at, total_pages_ref):
        self.report_title = report_title
        self.generated_at = generated_at
        self.total_pages_ref = total_pages_ref

    def __call__(self, canvas, doc):
        canvas.saveState()
        W, H = A4[1], A4[0]   # landscape: width=H, height=W of A4

        # ── Top accent bar ──
        canvas.setFillColor(C_GREEN)
        canvas.rect(0, H - 8*mm, W, 8*mm, fill=1, stroke=0)

        # ── Footer ──
        canvas.setFillColor(C_CREAM)
        canvas.rect(0, 0, W, 10*mm, fill=1, stroke=0)
        canvas.setFillColor(C_INK_MUTED)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(15*mm, 3.5*mm, f'Sports Academy  |  {self.report_title}  |  Generated: {self.generated_at}')
        canvas.drawRightString(W - 15*mm, 3.5*mm, f'Page {doc.page}')

        # ── Thin border line above footer ──
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(15*mm, 10*mm, W - 15*mm, 10*mm)

        canvas.restoreState()


# ════════════════════════════════════════════════════════════════════
#  SUMMARY BOX builder
# ════════════════════════════════════════════════════════════════════

def _summary_table(students, st, total_fee=None, total_paid=None, total_due=None):
    total     = len(students)
    active    = sum(1 for s in students if s.status == 'active')
    expired   = sum(1 for s in students if s.status == 'expired')

    # Use passed-in aggregates if available, else fall back to field sums
    if total_fee is None:
        total_fee = sum(float(s.total_fee) for s in students)
    if total_paid is None:
        total_paid = sum(float(s.fee_paid) for s in students)
    if total_due is None:
        total_due = sum(float(s.fee_due) for s in students)

    other = total - active - expired  # suspended etc.

    def _box(label, value, vstyle):
        return [Paragraph(label, st['summary_label']),
                Paragraph(value, st[vstyle])]

    data = [[
        _box('Total Students',    str(total),                   'summary_val'),
        _box('Active',            str(active),                  'summary_val_green'),
        _box('Expired/Suspended', str(expired + other),         'summary_val'),
        _box('Total Fee',         f'Rs.{float(total_fee):,.0f}','summary_val'),
        _box('Total Collected',   f'Rs.{float(total_paid):,.0f}','summary_val_green'),
        _box('Total Outstanding', f'Rs.{float(total_due):,.0f}',
             'summary_val_red' if float(total_due) > 0 else 'summary_val_green'),
    ]]

    col_w = [45*mm] * 6
    tbl = Table(data, colWidths=col_w, rowHeights=[24*mm])
    tbl.setStyle(TableStyle([
        ('BOX',         (0,0), (-1,-1), 0.5, C_BORDER),
        ('INNERGRID',   (0,0), (-1,-1), 0.5, C_BORDER),
        ('BACKGROUND',  (0,0), (-1,-1), C_CREAM),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING',  (0,0), (-1,-1), 8),
    ]))
    return tbl

# ════════════════════════════════════════════════════════════════════
#  FEE STATUS helper
# ════════════════════════════════════════════════════════════════════

def _fee_status(student):
    due  = float(student.fee_due)
    paid = float(student.fee_paid)
    if due == 0 and paid > 0:
        return ('Paid', C_GREEN)
    elif paid == 0:
        return ('Unpaid', C_RED)
    else:
        return ('Partial', C_AMBER)


# ════════════════════════════════════════════════════════════════════
#  MAIN TABLE builder
# ════════════════════════════════════════════════════════════════════

def _data_table(students, cols, st):
    """Build the main data table with auto-fit column widths (NO CUT ISSUE)."""

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm

    # Column definition: (key, header, width_mm, align)
    ALL_COLS = [
        ('col_id',         '#',            18, 'CENTER'),
        ('col_name',       'Student Name', 38, 'LEFT'),
        ('col_sport',      'Sport',        28, 'LEFT'),
        ('col_batch',      'Batch',        28, 'LEFT'),
        ('col_level',      'Level',        22, 'CENTER'),
        ('col_duration',   'Duration',     22, 'CENTER'),
        ('col_coach',      'Coach',        30, 'LEFT'),
        ('col_timeslot',   'Time',         20, 'CENTER'),
        ('col_contact',    'Contact',      28, 'LEFT'),
        ('col_admission',  'Admitted',     22, 'CENTER'),
        ('col_expiry',     'Expiry',       22, 'CENTER'),
        ('col_total_fee',  'Total Fee',    24, 'RIGHT'),
        ('col_fee_paid',   'Paid',         22, 'RIGHT'),
        ('col_fee_due',    'Due',          22, 'RIGHT'),
        ('col_fee_status', 'Fee Status',   22, 'CENTER'),
        ('col_status',     'Status',       20, 'CENTER'),
        ('col_parent',     'Parent',       30, 'LEFT'),
        ('col_whatsapp',   'WhatsApp',     28, 'LEFT'),
        ('col_gender',     'Gender',       16, 'CENTER'),
    ]

    # Filter selected columns
    active_cols = [(k, h, w, a) for (k, h, w, a) in ALL_COLS if cols.get(k)]

    if not active_cols:
        active_cols = ALL_COLS[:8]

    # # 🚀 LIMIT columns (optional but recommended)
    # if len(active_cols) > 12:
    #     active_cols = active_cols[:12]
    if 'col_fee_paid' not in [c[0] for c in active_cols]:
        for col in ALL_COLS:
            if col[0] == 'col_fee_paid':
                active_cols.append(col)
    # ─────────────────────────────────────────────
    # ✅ AUTO WIDTH FIX (IMPORTANT)
    # ─────────────────────────────────────────────
    PAGE_WIDTH = landscape(A4)[0]
    AVAILABLE_WIDTH = PAGE_WIDTH - (30 * mm)  # 15mm margins both sides

    raw_widths = [w for (_, _, w, _) in active_cols]
    total_raw_width = sum(raw_widths)

    scale = AVAILABLE_WIDTH / (total_raw_width * mm)

    col_widths = [(w * mm) * scale for w in raw_widths]
    # ─────────────────────────────────────────────

    # HEADER
    header = []
    for (_, hdr, _, al) in active_cols:
        header.append(Paragraph(
            hdr,
            ParagraphStyle(
                'th',
                fontName='Helvetica-Bold',
                fontSize=7,
                textColor=C_WHITE,
                alignment={'CENTER': TA_CENTER, 'RIGHT': TA_RIGHT}.get(al, TA_LEFT)
            )
        ))

    data_rows = [header]
    row_styles = []

    today = date.today()

    for idx, s in enumerate(students):
        bg = C_WHITE if idx % 2 == 0 else C_CREAM
        fee_label, _ = _fee_status(s)
        days_left = (s.subscription_expiry - today).days

        def _cell(text, style_key='cell_normal', align=None):
            style = st[style_key]
            if align:
                style = ParagraphStyle(
                    f"{style_key}_{align}",
                    parent=style,
                    alignment={'CENTER': TA_CENTER, 'RIGHT': TA_RIGHT}.get(align, TA_LEFT)
                )
            return Paragraph(str(text) if text else '—', style)

        row = []

        for (key, _, _, al) in active_cols:
            if key == 'col_id':
                row.append(_cell(s.student_id, 'cell_muted', al))
            elif key == 'col_name':
                row.append(_cell(s.full_name, 'cell_bold', al))
            elif key == 'col_sport':
                row.append(_cell(s.sport.name, 'cell_normal', al))
            elif key == 'col_batch':
                row.append(_cell(s.batch.name, 'cell_normal', al))
            elif key == 'col_level':
                row.append(_cell(s.expertise_level.name, 'cell_normal', al))
            elif key == 'col_duration':
                row.append(_cell(s.duration.duration_name, 'cell_normal', al))
            elif key == 'col_coach':
                row.append(_cell(
                    s.assigned_coach.full_name if s.assigned_coach else '—',
                    'cell_normal', al))
            elif key == 'col_timeslot':
                row.append(_cell(s.time_slot or '—', 'cell_muted', al))
            elif key == 'col_contact':
                row.append(_cell(s.contact_number, 'cell_normal', al))
            elif key == 'col_admission':
                row.append(_cell(s.admission_date.strftime('%d/%m/%y'), 'cell_muted', al))
            elif key == 'col_expiry':
                style = 'cell_red' if days_left <= 0 else (
                    'cell_amber' if days_left <= 15 else 'cell_normal'
                )
                row.append(_cell(s.subscription_expiry.strftime('%d/%m/%y'), style, al))
            elif key == 'col_total_fee':
                row.append(_cell(f'Rs.{float(s.total_fee):,.0f}', 'cell_normal', al))
            elif key == 'col_fee_paid':
                row.append(_cell(f'Rs.{float(s.fee_paid):,.0f}', 'cell_green', al))
            elif key == 'col_fee_due':
                style = 'cell_red' if float(s.fee_due) > 0 else 'cell_green'
                row.append(_cell(f'Rs.{float(s.fee_due):,.0f}', style, al))
            elif key == 'col_fee_status':
                row.append(_cell(fee_label, 'cell_normal', al))
            elif key == 'col_status':
                st_map = {
                    'active': 'cell_green',
                    'expired': 'cell_red',
                    'suspended': 'cell_amber'
                }
                row.append(_cell(s.get_status_display(), st_map.get(s.status), al))
            elif key == 'col_parent':
                row.append(_cell(s.parent_name, 'cell_normal', al))
            elif key == 'col_whatsapp':
                row.append(_cell(s.parent_whatsapp, 'cell_normal', al))
            elif key == 'col_gender':
                row.append(_cell(s.get_gender_display(), 'cell_muted', al))

        data_rows.append(row)

        r = idx + 1
        row_styles.append(('BACKGROUND', (0, r), (-1, r), bg))

    tbl = Table(data_rows, colWidths=col_widths, repeatRows=1)

    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), C_GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), C_WHITE),
        ('GRID', (0, 0), (-1, -1), 0.4, C_BORDER),

        ('FONTSIZE', (0, 1), (-1, -1), 7),   # smaller font
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),

        *row_styles
    ]))

    return tbl

# ════════════════════════════════════════════════════════════════════
#  FILTER SUMMARY TABLE  (shown below the main header in the PDF)
# ════════════════════════════════════════════════════════════════════

def _filters_table(filter_parts, st):
    if not filter_parts:
        return None
    items = []
    for part in filter_parts:
        label, val = part.split(': ', 1) if ': ' in part else (part, '')
        items.append([Paragraph(label, st['filter_label']),
                      Paragraph(val,   st['filter_val'])])
    # arrange in 3 columns
    row_data = []
    for i in range(0, len(items), 3):
        chunk = items[i:i+3]
        while len(chunk) < 3:
            chunk.append([Paragraph('', st['filter_label']), Paragraph('', st['filter_val'])])
        row_data.append([cell for pair in chunk for cell in pair])

    col_widths = [22*mm, 50*mm, 22*mm, 50*mm, 22*mm, 50*mm]
    tbl = Table(row_data, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ('FONTNAME',     (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',     (0,0), (-1,-1), 8),
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 4),
        ('TOPPADDING',   (0,0), (-1,-1), 3),
        ('BOTTOMPADDING',(0,0), (-1,-1), 3),
        ('BACKGROUND',   (0,0), (-1,-1), C_GOLD_PALE),
        ('BOX',          (0,0), (-1,-1), 0.5, C_BORDER),
        ('INNERGRID',    (0,0), (-1,-1), 0.3, C_BORDER),
    ]))
    return tbl


# ════════════════════════════════════════════════════════════════════
#  PDF BUILDER
# ════════════════════════════════════════════════════════════════════

def _build_pdf(students, params, report_type, cols,
               total_fee=None, total_paid=None, total_due=None):  # ← new params
    buffer = BytesIO()
    pw, ph = landscape(A4)
    margin = 15 * mm

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=20 * mm,
        bottomMargin=16 * mm,
    )

    st = _styles()
    today_str = date.today().strftime('%d %B %Y')
    now_str   = timezone.localtime().strftime('%d %b %Y, %I:%M %p')
    print("i want: ",now_str)
    REPORT_NAMES = {
        'student': 'Student Report',
        'fee':     'Fee Collection Report',
        'expiry':  'Subscription Expiry Report',
    }
    report_title = REPORT_NAMES.get(report_type, 'Student Report')

    canvas_cb = ReportCanvas(report_title, now_str, [None])
    filter_parts = _active_filters_text(params)

    story = []

    # ── Title block ──
    story.append(Spacer(1, 2*mm))
    title_data = [[
        Paragraph('SPORTS ACADEMY', ParagraphStyle('acad',
            fontName='Helvetica-Bold', fontSize=9, textColor=C_GREEN, leading=12)),
        Paragraph(report_title, st['title']),
        Paragraph(f'Generated: {now_str}', ParagraphStyle('gen',
            fontName='Helvetica', fontSize=8, textColor=C_INK_MUTED,
            leading=11, alignment=TA_RIGHT)),
    ]]
    title_tbl = Table(title_data, colWidths=[50*mm, pw - 2*margin - 100*mm, 50*mm])
    title_tbl.setStyle(TableStyle([
        ('VALIGN',      (0,0),(-1,-1), 'BOTTOM'),
        ('LEFTPADDING', (0,0),(-1,-1), 0),
        ('RIGHTPADDING',(0,0),(-1,-1), 0),
    ]))
    story.append(title_tbl)
    story.append(HRFlowable(width='100%', thickness=1.5, color=C_GREEN, spaceAfter=6))

    # ── Active filters row ──
    if filter_parts:
        ft = _filters_table(filter_parts, st)
        if ft:
            story.append(ft)
            story.append(Spacer(1, 4*mm))
    else:
        story.append(Paragraph('Filters: None applied — showing all students',
            ParagraphStyle('nf', fontName='Helvetica-Oblique', fontSize=8,
                           textColor=C_INK_MUTED, leading=11)))
        story.append(Spacer(1, 4*mm))

    # ── Summary boxes — pass the correct aggregates ──
    story.append(_summary_table(
        students, st,
        total_fee=total_fee,
        total_paid=total_paid,
        total_due=total_due,
    ))
    story.append(Spacer(1, 6*mm))

    # rest of function unchanged ...
    # ── Section header ──
    section_data = [[
        Paragraph(f'  {report_title.upper()}  —  {len(students)} RECORDS', st['section_head']),
        Paragraph(f'  {today_str}', ParagraphStyle('sh_r',
            fontName='Helvetica', fontSize=9, textColor=C_WHITE,
            leading=12, alignment=TA_RIGHT)),
    ]]
    section_tbl = Table(section_data, colWidths=[pw - 2*margin - 40*mm, 40*mm], rowHeights=[9*mm])
    section_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0,0),(-1,-1), C_INK_SOFT),
        ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',  (0,0),(-1,-1), 6),
        ('RIGHTPADDING', (0,0),(-1,-1), 6),
    ]))
    story.append(section_tbl)
    story.append(Spacer(1, 1*mm))

    if students:
        story.append(_data_table(students, cols, st))
    else:
        story.append(Spacer(1, 10*mm))
        story.append(Paragraph('No records match the selected filters.',
            ParagraphStyle('empty', fontName='Helvetica-Oblique', fontSize=11,
                           textColor=C_INK_MUTED, leading=16, alignment=TA_CENTER)))

    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f'This report was generated on {now_str} by Sports Academy Management System. '
        f'Total {len(students)} record(s) shown.',
        st['footer']
    ))

    doc.build(story, onFirstPage=canvas_cb, onLaterPages=canvas_cb)
    buffer.seek(0)
    return buffer

# ════════════════════════════════════════════════════════════════════
#  VIEWS
# ════════════════════════════════════════════════════════════════════

@admin_required
def reports_page(request):
    """Render the filter/report builder page."""
    total_count = _build_queryset(request.GET).count()
    return render(request, 'reports/reports.html', {
        'user':        request.current_user,
        'sports':      Sport.objects.filter(is_active=True),
        'batches':     Batch.objects.filter(is_active=True),
        'levels':      ExpertiseLevel.objects.filter(is_active=True),
        'durations':   Duration.objects.filter(is_active=True),
        'coaches':     Coach.objects.filter(status='active'),
        'total_count': total_count,
    })


@admin_required
def report_count(request):
    """AJAX endpoint: returns count of matching students for current filters."""
    count = _build_queryset(request.GET).count()
    return JsonResponse({'count': count})


@admin_required
def report_pdf(request):
    """Generate and stream the PDF."""
    from decimal import Decimal
    from django.db.models import Sum

    params      = request.GET
    report_type = params.get('report_type', 'student')
    qs          = _build_queryset(params)
    students    = list(qs)

    # ── Columns selected ──
    col_keys = [
        'col_photo', 'col_id', 'col_name', 'col_sport', 'col_batch',
        'col_level', 'col_duration', 'col_coach', 'col_timeslot',
        'col_contact', 'col_admission', 'col_expiry', 'col_total_fee',
        'col_fee_paid', 'col_fee_due', 'col_fee_status', 'col_status',
        'col_parent', 'col_whatsapp', 'col_gender',
    ]
    cols = {k: params.get(k) for k in col_keys}
    if not any(cols.values()):
        cols = {k: '1' for k in col_keys}

    if not students:
        return redirect(f"{request.META.get('HTTP_REFERER', '/reports/')}?error=no_results")

    # ── Aggregate the same way the payments page does ──
    student_pks = qs.values_list('pk', flat=True)

    total_paid = Payment.objects.filter(
        student_id__in=student_pks
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    total_due = qs.filter(total_fee__gt=0).aggregate(
        t=Sum('fee_due')
    )['t'] or Decimal('0')

    total_fee = total_paid + total_due

    buffer = _build_pdf(
        students, params, report_type, cols,
        total_fee=total_fee,
        total_paid=total_paid,
        total_due=total_due,
    )

    REPORT_NAMES = {
        'student': 'Student_Report',
        'fee':     'Fee_Collection_Report',
        'expiry':  'Expiry_Report',
    }
    filename = f"SportsAcademy_{REPORT_NAMES.get(report_type,'Report')}_{date.today().strftime('%Y%m%d')}.pdf"

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response