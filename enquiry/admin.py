from django.contrib import admin
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from django.urls import reverse, path
from django.contrib import messages

from .models import Enquiry
from .whatsapp import send_enquiry_whatsapp


class WhatsAppSentFilter(admin.SimpleListFilter):
    title = 'WhatsApp Notification'
    parameter_name = 'whatsapp_sent'

    def lookups(self, request, model_admin):
        return [('yes', 'Sent ✅'), ('no', 'Not Sent ❌')]

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(whatsapp_sent=True)
        if self.value() == 'no':
            return queryset.filter(whatsapp_sent=False)


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    # ── List view ──────────────────────────────────────────────────────────
    list_display  = (
        'full_name', 'phone', 'email_display', 'sport', 'age',
        'status_badge', 'whatsapp_badge', 'created_at', 'send_wa_button',
    )
    list_filter   = ('status', 'sport', WhatsAppSentFilter, 'created_at')
    search_fields = ('full_name', 'phone', 'email', 'sport', 'message')
    list_per_page = 25
    date_hierarchy = 'created_at'

    # ── Detail view ────────────────────────────────────────────────────────
    readonly_fields = ('created_at', 'updated_at', 'whatsapp_sent')
    fieldsets = (
        ('Contact Details', {
            'fields': ('full_name', 'phone', 'email', 'age'),
        }),
        ('Enquiry', {
            'fields': ('sport', 'message'),
        }),
        ('Admin', {
            'fields': ('status', 'whatsapp_sent', 'created_at', 'updated_at'),
        }),
    )

    # ── Actions ────────────────────────────────────────────────────────────
    actions = ['mark_contacted', 'mark_enrolled', 'resend_whatsapp']

    def mark_contacted(self, request, queryset):
        updated = queryset.update(status='contacted')
        self.message_user(request, f"{updated} enquir{'y' if updated == 1 else 'ies'} marked as Contacted.")
    mark_contacted.short_description = "Mark selected as Contacted"

    def mark_enrolled(self, request, queryset):
        updated = queryset.update(status='enrolled')
        self.message_user(request, f"{updated} enquir{'y' if updated == 1 else 'ies'} marked as Enrolled.")
    mark_enrolled.short_description = "Mark selected as Enrolled"

    def resend_whatsapp(self, request, queryset):
        sent_count = 0
        for enquiry in queryset:
            if send_enquiry_whatsapp(enquiry):
                enquiry.whatsapp_sent = True
                enquiry.save(update_fields=['whatsapp_sent'])
                sent_count += 1
        self.message_user(
            request,
            f"WhatsApp notification sent for {sent_count} of {queryset.count()} enquiries.",
            messages.SUCCESS if sent_count else messages.WARNING,
        )
    resend_whatsapp.short_description = "📲 Resend WhatsApp notification"

    # ── Custom columns ─────────────────────────────────────────────────────
    def email_display(self, obj):
        if obj.email:
            return format_html('<a href="mailto:{}">{}</a>', obj.email, obj.email)
        return '—'
    email_display.short_description = 'Email'

    STATUS_COLORS = {
        'new':       ('#1a73e8', '#e8f0fe'),
        'contacted': ('#f57c00', '#fff3e0'),
        'enrolled':  ('#1e8e3e', '#e6f4ea'),
        'closed':    ('#5f6368', '#f1f3f4'),
    }

    def status_badge(self, obj):
        color, bg = self.STATUS_COLORS.get(obj.status, ('#333', '#eee'))
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def whatsapp_badge(self, obj):
        if obj.whatsapp_sent:
            return format_html('<span style="color:#1e8e3e;font-weight:600;">✅ Sent</span>')
        return format_html('<span style="color:#d32f2f;font-weight:600;">❌ Pending</span>')
    whatsapp_badge.short_description = 'WhatsApp'

    def send_wa_button(self, obj):
        url = reverse('admin:send_whatsapp', args=[obj.pk])
        return format_html(
            '<a href="{}" style="background:#25D366;color:#fff;padding:4px 10px;'
            'border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;">'
            '📲 Send WA</a>',
            url
        )
    send_wa_button.short_description = 'Notify'

    # ── Custom URL for single-item WhatsApp send ───────────────────────────
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:pk>/send-whatsapp/',
                self.admin_site.admin_view(self.send_whatsapp_view),
                name='send_whatsapp',
            )
        ]
        return custom + urls

    def send_whatsapp_view(self, request, pk):
        from django.shortcuts import get_object_or_404
        enquiry = get_object_or_404(Enquiry, pk=pk)
        sent = send_enquiry_whatsapp(enquiry)
        if sent:
            enquiry.whatsapp_sent = True
            enquiry.save(update_fields=['whatsapp_sent'])
            self.message_user(request, f"WhatsApp sent to {enquiry.full_name} successfully ✅", messages.SUCCESS)
        else:
            self.message_user(request, "WhatsApp send failed. Check Twilio credentials in settings.py.", messages.ERROR)
        return HttpResponseRedirect(reverse('admin:enquiry_enquiry_changelist'))
