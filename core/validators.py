"""
validators.py — Sports Academy
Centralised backend validation for all forms.
Every validator returns a list of error strings (empty = valid).
"""
import re
from datetime import date
from .models import FeeStructures


# ─────────────────────────────────────────────────────────────────
#  PRIMITIVE VALIDATORS
# ─────────────────────────────────────────────────────────────────

def required(value, label):
    if not str(value).strip():
        return [f'{label} is required.']
    return []


def min_length(value, n, label):
    if len(str(value).strip()) < n:
        return [f'{label} must be at least {n} characters.']
    return []


def max_length(value, n, label):
    if len(str(value).strip()) > n:
        return [f'{label} must be no more than {n} characters.']
    return []


def is_alpha_name(value, label):
    """Allows letters, spaces, hyphens, apostrophes, dots."""
    if not re.match(r"^[A-Za-z\s\-\.']+$", str(value).strip()):
        return [f'{label} must contain only letters, spaces, hyphens or apostrophes.']
    return []


def is_phone(value, label):
    """10-15 digits, optional leading +."""
    cleaned = re.sub(r'[\s\-\(\)]', '', str(value).strip())
    if not re.match(r'^\+?\d{10,15}$', cleaned):
        return [f'{label} must be a valid phone number (10–15 digits).']
    return []


def is_email(value, label):
    if value and not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', str(value).strip()):
        return [f'{label} must be a valid email address.']
    return []


def is_positive_number(value, label):
    try:
        if float(value) < 0:
            return [f'{label} must be a positive number.']
    except (ValueError, TypeError):
        return [f'{label} must be a valid number.']
    return []


def is_percentage(value, label):
    try:
        v = float(value)
        if not (0 <= v <= 100):
            return [f'{label} must be between 0 and 100.']
    except (ValueError, TypeError):
        return [f'{label} must be a valid number.']
    return []


def is_date(value, label):
    if not value:
        return []
    try:
        if isinstance(value, str):
            date.fromisoformat(value)
    except ValueError:
        return [f'{label} must be a valid date (YYYY-MM-DD).']
    return []


def date_not_future(value, label):
    try:
        d = date.fromisoformat(str(value)) if isinstance(value, str) else value
        if d > date.today():
            return [f'{label} cannot be a future date.']
    except Exception:
        pass
    return []


def date_not_past(value, label):
    try:
        d = date.fromisoformat(str(value)) if isinstance(value, str) else value
        if d < date.today():
            return [f'{label} cannot be a past date.']
    except Exception:
        pass
    return []


def minimum_age(dob_value, min_years, label='Date of Birth'):
    try:
        dob = date.fromisoformat(str(dob_value)) if isinstance(dob_value, str) else dob_value
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < min_years:
            return [f'{label}: student must be at least {min_years} years old.']
        if age > 100:
            return [f'{label}: please enter a valid date of birth.']
    except Exception:
        pass
    return []


def passwords_match(pw1, pw2):
    if pw1 != pw2:
        return ['Passwords do not match.']
    return []


def strong_password(value):
    errs = []
    errs += min_length(value, 6, 'Password')
    return errs


def no_special_chars_username(value):
    if not re.match(r'^[A-Za-z0-9_\.@]+$', str(value).strip()):
        return ['Username can only contain letters, numbers, underscores, dots and @.']
    return []


# ─────────────────────────────────────────────────────────────────
#  COMPOSITE FORM VALIDATORS
#  Each returns a dict: {'field_name': ['error1', ...], ...}
#  Use collect() to flatten into a list for messages.
# ─────────────────────────────────────────────────────────────────

def collect(errors_dict):
    """Flatten {field: [errors]} → [error strings]"""
    flat = []
    for msgs in errors_dict.values():
        flat.extend(msgs)
    return flat


def validate_login(data):
    e = {}
    e['username'] = required(data.get('username', ''), 'Username')
    e['password'] = required(data.get('password', ''), 'Password')
    return {k: v for k, v in e.items() if v}


def validate_user_create(data, existing_username=None):
    e = {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    e['username']  = (required(username, 'Username') or
                      no_special_chars_username(username) or
                      min_length(username, 3, 'Username') or
                      max_length(username, 40, 'Username'))
    e['password']  = required(password, 'Password') or strong_password(password)
    e['password2'] = passwords_match(password, data.get('password2', ''))
    e['full_name'] = required(data.get('full_name', ''), 'Full name')
    e['role']      = required(data.get('role', ''), 'Role')

    return {k: v for k, v in e.items() if v}


def validate_coach(data):
    e = {}
    e['first_name']     = required(data.get('first_name',''), 'First name') or is_alpha_name(data.get('first_name',''), 'First name')
    e['last_name']      = required(data.get('last_name',''), 'Last name')   or is_alpha_name(data.get('last_name',''), 'Last name')
    e['gender']         = required(data.get('gender',''), 'Gender')
    e['contact_number'] = required(data.get('contact_number',''), 'Contact number') or is_phone(data.get('contact_number',''), 'Contact number')
    e['joining_date']   = required(data.get('joining_date',''), 'Joining date') or is_date(data.get('joining_date',''), 'Joining date')
    e['email']          = is_email(data.get('email',''), 'Email')
    e['salary_amount']  = is_positive_number(data.get('salary_amount', 0), 'Salary amount')
    e['experience_years'] = is_positive_number(data.get('experience_years', 0), 'Experience years')

    wa = data.get('whatsapp_number', '').strip()
    if wa:
        e['whatsapp_number'] = is_phone(wa, 'WhatsApp number')

    ep = data.get('emergency_phone', '').strip()
    if ep:
        e['emergency_phone'] = is_phone(ep, 'Emergency phone')

    dob = data.get('dob', '').strip()
    if dob:
        e['dob'] = is_date(dob, 'Date of birth') or date_not_future(dob, 'Date of birth')

    return {k: v for k, v in e.items() if v}


def validate_student_personal(data):
    e = {}
    e['first_name']     = required(data.get('first_name',''), 'First name') or is_alpha_name(data.get('first_name',''), 'First name')
    e['last_name']      = required(data.get('last_name',''), 'Last name')   or is_alpha_name(data.get('last_name',''), 'Last name')
    e['dob']            = (required(data.get('dob',''), 'Date of birth') or
                           is_date(data.get('dob',''), 'Date of birth') or
                           date_not_future(data.get('dob',''), 'Date of birth') or
                           minimum_age(data.get('dob',''), 3))
    e['gender']         = required(data.get('gender',''), 'Gender')
    e['contact_number'] = (required(data.get('contact_number',''), 'Contact number') or
                           is_phone(data.get('contact_number',''), 'Contact number'))
    e['address']        = required(data.get('address',''), 'Address') or min_length(data.get('address',''), 10, 'Address')
    e['email']          = is_email(data.get('email',''), 'Email')
    return {k: v for k, v in e.items() if v}


def validate_student_parent(data):
    e = {}
    e['parent_name']    = (required(data.get('parent_name',''), 'Parent name') or
                           is_alpha_name(data.get('parent_name',''), 'Parent name'))
    e['parent_whatsapp']= (required(data.get('parent_whatsapp',''), 'Parent WhatsApp') or
                           is_phone(data.get('parent_whatsapp',''), 'Parent WhatsApp'))
    e['parent_email']   = is_email(data.get('parent_email',''), 'Parent email')
    ep = data.get('emergency_contact','').strip()
    if ep:
        e['emergency_contact'] = is_phone(ep, 'Emergency contact')
    return {k: v for k, v in e.items() if v}


def validate_student_sport(data):
    e = {}
    e['sport']            = required(data.get('sport',''), 'Sport')
    e['batch']            = required(data.get('batch',''), 'Batch')
    e['expertise_level']  = required(data.get('expertise_level',''), 'Expertise level')
    e['duration']         = required(data.get('duration',''), 'Duration')
    e['admission_date']   = (required(data.get('admission_date',''), 'Admission date') or
                             is_date(data.get('admission_date',''), 'Admission date'))
    fee_paid = data.get('fee_paid', '0')
    if fee_paid:
        e['fee_paid'] = is_positive_number(fee_paid, 'Fee paid')
    return {k: v for k, v in e.items() if v}


def validate_sport(data, existing_pk=None):
    from .models import Sport
    e = {}
    name = data.get('name', '').strip()
    e['name'] = required(name, 'Sport name') or max_length(name, 100, 'Sport name')
    if not e.get('name'):
        qs = Sport.objects.filter(name__iexact=name)
        if existing_pk:
            qs = qs.exclude(pk=existing_pk)
        if qs.exists():
            e['name'] = [f'A sport named "{name}" already exists.']
    e['icon'] = required(data.get('icon',''), 'Icon')
    return {k: v for k, v in e.items() if v}


def validate_batch(data, existing_pk=None):
    from .models import Batch
    e = {}
    name = data.get('name', '').strip()
    e['name'] = required(name, 'Batch name') or max_length(name, 100, 'Batch name')
    if not e.get('name'):
        qs = Batch.objects.filter(name__iexact=name)
        if existing_pk:
            qs = qs.exclude(pk=existing_pk)
        if qs.exists():
            e['name'] = [f'Batch "{name}" already exists.']
    e['batch_type']    = required(data.get('batch_type',''), 'Batch type')
    e['days_per_week'] = is_positive_number(data.get('days_per_week', 0), 'Days per week')
    return {k: v for k, v in e.items() if v}


def validate_expertise_level(data, existing_pk=None):
    from .models import ExpertiseLevel
    e = {}
    name = data.get('name', '').strip()
    e['name'] = required(name, 'Level name') or max_length(name, 100, 'Level name')
    if not e.get('name'):
        qs = ExpertiseLevel.objects.filter(name__iexact=name)
        if existing_pk:
            qs = qs.exclude(pk=existing_pk)
        if qs.exists():
            e['name'] = [f'Level "{name}" already exists.']
    color = data.get('color_hex', '').strip()
    if color and not re.match(r'^#[0-9A-Fa-f]{6}$', color):
        e['color_hex'] = ['Color must be a valid hex code (e.g. #3A7A52).']
    return {k: v for k, v in e.items() if v}


def validate_fee_structure(data, existing_pk=None):
    e = {}
    for field, label in [('sport','Sport'),('batch','Batch'),('expertise_level','Expertise level'),('duration','Duration')]:
        e[field] = required(data.get(field,''), label)
    e['fee_amount']    = required(data.get('fee_amount',''), 'Fee amount') or is_positive_number(data.get('fee_amount',0), 'Fee amount')
    e['effective_date']= required(data.get('effective_date',''), 'Effective date') or is_date(data.get('effective_date',''), 'Effective date')
    e['discount_pct']  = is_percentage(data.get('discount_pct', 0), 'Discount')

    if not any(e.values()):
        qs = FeeStructures.objects.filter(
            sport_id=data.get('sport'), batch_id=data.get('batch'),
            expertise_level_id=data.get('expertise_level'), duration_id=data.get('duration'),
        )
        if existing_pk:
            qs = qs.exclude(pk=existing_pk)
        if qs.exists():
            e['__all__'] = ['A fee entry for this combination already exists.']

    return {k: v for k, v in e.items() if v}


def validate_password_reset(data):
    e = {}
    pw = data.get('new_password', '').strip()
    e['new_password'] = required(pw, 'New password') or strong_password(pw)
    return {k: v for k, v in e.items() if v}
