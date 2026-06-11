# yourapp/context_processors.py
from datetime import date, timedelta
from .models import StudentData, Coach

def sidebar_counts(request):
    if not request.session.get('user_id'):
        return {}
    try:
        today = date.today()
        week_end = today + timedelta(days=7)
        return {
            'total_students': StudentData.objects.filter(status='active').count(),
            'coach_count':    Coach.objects.filter(status='active').count(),
            'notif_count':    StudentData.objects.filter(
                                  status='active',
                                  subscription_expiry__gte=today,
                                  subscription_expiry__lte=week_end,
                              ).count(),
        }
    except Exception:
        return {}