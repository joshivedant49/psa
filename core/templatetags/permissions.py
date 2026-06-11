from django import template
from core.models import CoachPermission, SystemUser

register = template.Library()


@register.filter
def has_module_permission(user, module):

    # No user
    if not user:
        return False

    # Ensure correct user model
    if not isinstance(user, SystemUser):
        return False

    # Admin bypass
    if user.is_admin:
        return True

    return CoachPermission.objects.filter(
        user=user,
        module=module,
        allowed=True
    ).exists()