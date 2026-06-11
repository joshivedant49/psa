import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST,require_GET
from django.views.decorators.csrf import csrf_exempt
# from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator

from .models import Enquiry
from .whatsapp import send_enquiry_whatsapp
from django.shortcuts import redirect
from django.contrib import messages
from .forms import EnquiryForm
from core.views import login_required 
logger = logging.getLogger(__name__)


@require_POST
def submit_enquiry(request):
    """
    Accepts the enquiry form via AJAX (JSON response) or normal POST.
    Saves to DB, then fires a WhatsApp notification to the admin.
    """
    form = EnquiryForm(request.POST)

    if form.is_valid():
        enquiry = form.save()

        # Fire WhatsApp notification
        sent = send_enquiry_whatsapp(enquiry)
        enquiry.whatsapp_sent = sent
        enquiry.save(update_fields=['whatsapp_sent'])

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Thank you! We will contact you within 24 hours.',
                'whatsapp_sent': sent,
            })

        # Fallback: normal POST redirect
        from django.shortcuts import redirect
        from django.contrib import messages
        messages.success(request, "Enquiry submitted! We'll be in touch soon.")
        return redirect('/#contact')

    # Form invalid
    errors = form.errors.as_json()
    logger.warning(f"Enquiry form invalid: {errors}")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)

    
    messages.error(request, "Please fill in all required fields correctly.")
    return redirect('/#contact')


@login_required
def enquiry_dashboard(request):
    """
    Main enquiry dashboard for admin staff.
    URL: /admin/enquiries/
    """
    # ── Counts (always full, ignore filters) ──────────────────
    total_count    = Enquiry.objects.count()
    new_count      = Enquiry.objects.filter(status='new').count()
    pending_count  = Enquiry.objects.filter(status='contacted').count()
    enrolled_count = Enquiry.objects.filter(status='enrolled').count()
    closed_count   = Enquiry.objects.filter(status='closed').count()
    done_count     = enrolled_count + closed_count

    # ── Base queryset ─────────────────────────────────────────
    qs = Enquiry.objects.all()

    # Hide responded/closed unless show_all is toggled
    show_all = request.GET.get('show_all') == '1'
    if not show_all:
        qs = qs.exclude(status__in=['closed'])

    # Status filter
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    # Sport filter
    sport = request.GET.get('sport', '')
    if sport:
        qs = qs.filter(sport=sport)

    # Search
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q) |
            Q(phone__icontains=q)     |
            Q(email__icontains=q)     |
            Q(sport__icontains=q)
        )

    # Distinct sports for filter chips
    sports_list = (
        Enquiry.objects
        .exclude(sport='')
        .values_list('sport', flat=True)
        .distinct()
        .order_by('sport')
    )

    # Paginate
    paginator   = Paginator(qs, 25)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)

    # Build query string for pagination links (exclude page)
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    return render(request, 'admin/enquiry/enquiry_dashboard.html', {
        'enquiries':      page_obj,
        'page_obj':       page_obj,
        'is_paginated':   page_obj.has_other_pages(),
        'query_string':   query_string,
        'show_all':       show_all,
        'sports_list':    sports_list,
        # Counts
        'total_count':    total_count,
        'new_count':      new_count,
        'pending_count':  pending_count,
        'enrolled_count': enrolled_count,
        'closed_count':   closed_count,
        'done_count':     done_count,
        'user': request.current_user,
    })


@login_required
@require_POST
def enquiry_bulk_action(request):
    """
    JSON endpoint for bulk actions from the dashboard.
    URL: /admin/enquiries/bulk/
    """
    try:
        body   = json.loads(request.body)
        action = body.get('action')
        ids    = body.get('ids', [])

        if not ids:
            return JsonResponse({'success': False, 'error': 'No enquiries selected'}, status=400)

        qs = Enquiry.objects.filter(pk__in=ids)

        if action == 'mark_responded':
            count = qs.update(status='closed')
            return JsonResponse({'success': True, 'count': count})

        elif action == 'mark_status':
            status = body.get('status', 'contacted')
            if status not in ['new', 'contacted', 'enrolled', 'closed']:
                return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)
            count = qs.update(status=status)
            return JsonResponse({'success': True, 'count': count})

        elif action == 'send_whatsapp':
            sent = 0
            for enquiry in qs:
                if send_enquiry_whatsapp(enquiry):
                    enquiry.whatsapp_sent = True
                    enquiry.save(update_fields=['whatsapp_sent'])
                    sent += 1
            return JsonResponse({'success': True, 'sent': sent, 'total': len(ids)})

        else:
            return JsonResponse({'success': False, 'error': 'Unknown action'}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
