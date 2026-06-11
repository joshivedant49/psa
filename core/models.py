from django.db import models
import uuid
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password as django_check_password
import json


class Sport(models.Model):
    ICON_CHOICES = [
        ('🏸', 'Badminton'),
        ('🎾', 'Tennis'),
        ('⚽', 'Football'),
        ('⛸️', 'Skating'),
        ('♟️', 'Chess'),
        ('🏊', 'Swimming'),
        ('🏓', 'Table Tennis'),
        ('🥊', 'Boxing'),
        ('🤸', 'Gymnastics'),
        ('🏋️', 'Weightlifting'),
        ('🎯', 'Archery'),
        ('🏐', 'Volleyball'),
        ('🏀', 'Basketball'),
        ('🎱', 'Billiards'),
        ('🥋', 'Martial Arts'),
    ]

    name        = models.CharField(max_length=100, unique=True)
    icon        = models.CharField(max_length=10, choices=ICON_CHOICES, default='🏸')
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Batch(models.Model):
    BATCH_TYPE_CHOICES = [
        ('regular',   'Regular'),
        ('alternate', 'Alternate'),
        ('day_based', 'Day-Based'),
        ('weekend',   'Weekend'),
        ('intensive', 'Intensive'),
        ('custom',    'Custom'),
    ]

    DAYS_PER_WEEK_CHOICES = [(i, f'{i} day{"s" if i > 1 else ""} / week') for i in range(1, 8)]

    name          = models.CharField(max_length=100, unique=True)
    batch_type    = models.CharField(max_length=20, choices=BATCH_TYPE_CHOICES, default='regular')
    days_per_week = models.PositiveSmallIntegerField(choices=DAYS_PER_WEEK_CHOICES, default=6)
    description   = models.TextField(blank=True)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Batches'

    def __str__(self):
        return self.name

    @property
    def type_label(self):
        return dict(self.BATCH_TYPE_CHOICES).get(self.batch_type, self.batch_type)


class ExpertiseLevel(models.Model):
    ORDER_CHOICES = [(i, str(i)) for i in range(1, 11)]

    name            = models.CharField(max_length=100, unique=True)
    order           = models.PositiveSmallIntegerField(
                          choices=ORDER_CHOICES, default=1,
                          help_text='Display order (1 = first / most basic)')
    description     = models.TextField(blank=True)
    color_hex       = models.CharField(
                          max_length=7, default='#3A7A52',
                          help_text='Hex color used for UI badge, e.g. #3A7A52')
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name        = 'Expertise Level'
        verbose_name_plural = 'Expertise Levels'

    def __str__(self):
        return self.name

class Duration(models.Model):

    duration_name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['duration_name']

    def __str__(self):
        return self.duration_name

# class FeeStructure(models.Model):
#     sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
#     batch = models.ForeignKey(Batch, on_delete=models.CASCADE)
#     expertise = models.ForeignKey(ExpertiseLevel, on_delete=models.CASCADE)
#     duration = models.ForeignKey(Duration, on_delete=models.CASCADE)
#     fees = models.DecimalField(max_digits=10, decimal_places=2)

#     class Meta:
#         unique_together = ('sport', 'batch', 'expertise', 'duration')

#     def __str__(self):
#         return f"{self.sport} - {self.batch} - {self.duration}"


class FeeStructures(models.Model):
    sport=models.ForeignKey(Sport,on_delete=models.PROTECT,related_name='fee_structures')
    batch=models.ForeignKey(Batch,on_delete=models.PROTECT,related_name='fee_structures')
    expertise_level=models.ForeignKey(ExpertiseLevel,on_delete=models.PROTECT,related_name='fee_structures')
    duration=models.ForeignKey(Duration,on_delete=models.PROTECT,related_name='fee_structures')
    fee_amount=models.DecimalField(max_digits=10,decimal_places=2)
    discount_pct=models.DecimalField(max_digits=5,decimal_places=2,default=0)
    is_active=models.BooleanField(default=True)
    effective_date=models.DateField()
    notes=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['sport__name','batch__name','expertise_level__order','duration__duration_name']
        unique_together=('sport','batch','expertise_level','duration')
        verbose_name='Fee Structure'; verbose_name_plural='Fee Structures'
    def __str__(self): return f'{self.sport}|{self.batch}|{self.expertise_level}|{self.duration}—₹{self.fee_amount}'
    @property
    def discounted_amount(self):
        if self.discount_pct: return round(float(self.fee_amount)*(1-float(self.discount_pct)/100),2)
        return float(self.fee_amount)

class SystemUser(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('coach', 'Coach'),
    ]

    username         = models.CharField(max_length=60, unique=True)
    password_hash    = models.CharField(max_length=256)   # PBKDF2 encrypted
    role             = models.CharField(max_length=10, choices=ROLE_CHOICES, default='coach')
    full_name        = models.CharField(max_length=120)
    email            = models.EmailField(blank=True)
    is_active        = models.BooleanField(default=True)
    last_login       = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    # Link to Coach profile (null for admin users)
    coach            = models.OneToOneField(
                           'Coach', on_delete=models.SET_NULL,
                           null=True, blank=True, related_name='user_account')

    class Meta:
        ordering = ['username']
        verbose_name = 'System User'
        verbose_name_plural = 'System Users'

    def __str__(self): return f'{self.username} ({self.role})'

    def set_password(self, raw_password):
        """Hash and store password using Django's PBKDF2 hasher."""
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        """Verify raw password against stored hash."""
        return django_check_password(raw_password, self.password_hash)

    @property
    def is_admin(self): return self.role == 'admin'
    @property
    def is_coach(self): return self.role == 'coach'

class CoachPermission(models.Model):
    """Stores which modules a coach user is allowed to access."""

    MODULE_CHOICES = [
        ('dashboard',        'Dashboard'),
        ('student_list',     'View Students'),
        ('student_admission','Admit Students'),
        ('attendance',       'Mark Attendance'),
        ('notifications',    'View Notifications'),
        ('fee_structure',    'View Fee Structure'),
        ('reports',          'View Reports'),
        ('coach_list',       'View Coaches'),
        ('Payments',    'View Payment Status')
    ]

    user    = models.ForeignKey(SystemUser, on_delete=models.CASCADE, related_name='permissions')
    module  = models.CharField(max_length=30, choices=MODULE_CHOICES)
    allowed = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'module')
        verbose_name = 'Coach Permission'
        verbose_name_plural = 'Coach Permissions'

    def __str__(self): return f'{self.user.username} → {self.module}: {"✓" if self.allowed else "✗"}'

class Coach(models.Model):
    GENDER_CHOICES=[('M','Male'),('F','Female'),('O','Other')]
    EMPLOYMENT_TYPE_CHOICES=[
        ('full_time','Full Time'),('part_time','Part Time'),
        ('freelance','Freelance / Visiting'),('contract','Contract'),
    ]
    SALARY_TYPE_CHOICES=[
        ('fixed','Fixed Monthly'),('per_batch','Per Batch'),('hourly','Hourly'),
    ]
    STATUS_CHOICES=[
        ('active','Active'),('inactive','Inactive'),
        ('on_leave','On Leave'),('terminated','Terminated'),
    ]

    coach_id        = models.CharField(max_length=20,unique=True,editable=False)
    first_name      = models.CharField(max_length=60)
    last_name       = models.CharField(max_length=60)
    dob             = models.DateField(blank=True,null=True)
    gender          = models.CharField(max_length=1,choices=GENDER_CHOICES)
    contact_number  = models.CharField(max_length=15)
    whatsapp_number = models.CharField(max_length=15,blank=True)
    email           = models.EmailField(blank=True)
    address         = models.TextField(blank=True)
    photo           = models.ImageField(upload_to='coaches/photos/',blank=True,null=True)
    sports_coached  = models.ManyToManyField(Sport,related_name='coaches',blank=True)
    expertise_levels= models.ManyToManyField(ExpertiseLevel,related_name='coaches',blank=True)
    qualification   = models.CharField(max_length=200,blank=True)
    experience_years= models.PositiveSmallIntegerField(default=0)
    joining_date    = models.DateField()
    employment_type = models.CharField(max_length=15,choices=EMPLOYMENT_TYPE_CHOICES,default='full_time')
    salary_type     = models.CharField(max_length=15,choices=SALARY_TYPE_CHOICES,default='fixed')
    salary_amount   = models.DecimalField(max_digits=10,decimal_places=2,default=0)
    emergency_name  = models.CharField(max_length=100,blank=True)
    emergency_phone = models.CharField(max_length=15,blank=True)
    emergency_relation = models.CharField(max_length=40,blank=True)
    id_proof        = models.FileField(upload_to='coaches/docs/',blank=True,null=True)
    certificate     = models.FileField(upload_to='coaches/docs/',blank=True,null=True)
    notes           = models.TextField(blank=True)
    status          = models.CharField(max_length=15,choices=STATUS_CHOICES,default='active')
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta: ordering=['first_name','last_name']; verbose_name='Coach'; verbose_name_plural='Coaches'
    def __str__(self): return f'{self.coach_id} — {self.full_name}'

    @property
    def full_name(self): return f'{self.first_name} {self.last_name}'
    @property
    def initials(self): return f'{self.first_name[:1]}{self.last_name[:1]}'.upper()
    @property
    def sports_list(self): return ', '.join(s.name for s in self.sports_coached.all())
    @property
    def employment_label(self): return dict(self.EMPLOYMENT_TYPE_CHOICES).get(self.employment_type,self.employment_type)
    @property
    def salary_label(self): return dict(self.SALARY_TYPE_CHOICES).get(self.salary_type,self.salary_type)
    @property
    def status_label(self): return dict(self.STATUS_CHOICES).get(self.status,self.status)
    @property
    def qr_data(self):
        return json.dumps({'id':self.coach_id,'name':self.full_name,'type':'coach','academy':'Sports Academy'})

    def save(self,*args,**kwargs):
        if not self.coach_id:
            year=timezone.now().year
            count=Coach.objects.filter(coach_id__startswith=f'CH{year}').count()+1
            self.coach_id=f'CH{year}{count:04d}'
        super().save(*args,**kwargs)

class StudentData(models.Model):
    GENDER_CHOICES = [('M','Male'),('F','Female'),('O','Other')]
    BLOOD_GROUP_CHOICES = [
        ('A+','A+'),('A-','A-'),('B+','B+'),('B-','B-'),
        ('O+','O+'),('O-','O-'),('AB+','AB+'),('AB-','AB-'),('NK','Not Known'),
    ]
    STATUS_CHOICES = [('active','Active'),('expired','Expired'),('suspended','Suspended')]

    # Auto-generated student ID
    student_id    = models.CharField(max_length=20, unique=True, editable=False)

    # ── Personal Details ──────────────────────────────────────
    first_name    = models.CharField(max_length=60)
    last_name     = models.CharField(max_length=60)
    dob           = models.DateField(verbose_name='Date of Birth')
    gender        = models.CharField(max_length=1, choices=GENDER_CHOICES)
    blood_group   = models.CharField(max_length=4, choices=BLOOD_GROUP_CHOICES, default='NK')
    contact_number= models.CharField(max_length=15)
    email         = models.EmailField(blank=True)
    address       = models.TextField()
    photo         = models.ImageField(upload_to='students/photos/', blank=True, null=True)

    # ── Parent / Guardian Details ─────────────────────────────
    parent_name       = models.CharField(max_length=100)
    parent_relation   = models.CharField(max_length=30, default='Father')
    parent_whatsapp   = models.CharField(max_length=15)
    parent_email      = models.EmailField(blank=True)
    parent_occupation = models.CharField(max_length=80, blank=True)
    emergency_contact = models.CharField(max_length=15, blank=True)

    # ── Sport Admission Details ───────────────────────────────
    sport           = models.ForeignKey('Sport',         on_delete=models.PROTECT, related_name='students')
    batch           = models.ForeignKey('Batch',         on_delete=models.PROTECT, related_name='students')
    expertise_level = models.ForeignKey('ExpertiseLevel',on_delete=models.PROTECT, related_name='students')
    duration        = models.ForeignKey('Duration',      on_delete=models.PROTECT, related_name='students')
    fee_structure   = models.ForeignKey('FeeStructures',  on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    assigned_coach = models.ForeignKey(Coach,on_delete=models.SET_NULL,null=True,blank=True,related_name='students')
    admission_date      = models.DateField()
    subscription_start  = models.DateField()
    subscription_expiry = models.DateField()
    time_slot           = models.CharField(max_length=50, blank=True)

    # ── Fee / Payment ─────────────────────────────────────────
    fee_paid      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fee_due       = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_fee     = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Status ───────────────────────────────────────────────
    status      = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active')
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    is_renewal = models.BooleanField(default=False)


    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'Student'
        verbose_name_plural = 'Students'

    def __str__(self): return f'{self.student_id} — {self.full_name}'

    @property
    def full_name(self): return f'{self.first_name} {self.last_name}'
    @property
    def initials(self): return f'{self.first_name[:1]}{self.last_name[:1]}'.upper()
    @property
    def days_until_expiry(self): return (self.subscription_expiry-timezone.now().date()).days
    @property
    def qr_data(self):
        return json.dumps({
            'id':self.student_id,'name':self.full_name,
            'sport':self.sport.name,'expiry':str(self.subscription_expiry),
            'type':'student','academy':'Sports Academy'
        })

    def save(self, *args, **kwargs):
        if not self.student_id:
            # Generate SA + year + 4-digit sequence  e.g. SA20240001
            year  = timezone.now().year
            count = StudentData.objects.filter(student_id__startswith=f'SA{year}').count() + 1
            self.student_id = f'SA{year}{count:04d}'
        super().save(*args, **kwargs)

class CoachAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent',  'Absent'),
        ('late',    'Late'),
        ('on_leave','On Leave'),
    ]
    METHOD_CHOICES = [
        ('manual', 'Manual'),
        ('qr',     'QR Scan'),
    ]

    coach          = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='attendance')
    date           = models.DateField()
    status         = models.CharField(max_length=10, choices=STATUS_CHOICES, default='present')
    check_in_time  = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    method         = models.CharField(max_length=10, choices=METHOD_CHOICES, default='manual')
    marked_by      = models.ForeignKey(SystemUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='coach_attendance_marked')
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('coach', 'date')
        ordering = ['-date', 'coach__first_name']
        verbose_name = 'Coach Attendance'
        verbose_name_plural = 'Coach Attendance'

    def __str__(self): return f'{self.coach.full_name} — {self.date} — {self.status}'


class StudentAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent',  'Absent'),
        ('late',    'Late'),
        ('excused', 'Excused'),
    ]
    METHOD_CHOICES = [
        ('manual', 'Manual'),
        ('qr',     'QR Scan'),
    ]

    student        = models.ForeignKey(StudentData, on_delete=models.CASCADE, related_name='attendance')
    date           = models.DateField()
    status         = models.CharField(max_length=10, choices=STATUS_CHOICES, default='present')
    assigned_slot  = models.CharField(max_length=50, blank=True)
    attended_slot  = models.CharField(max_length=50, blank=True)
    is_override    = models.BooleanField(default=False)
    method         = models.CharField(max_length=10, choices=METHOD_CHOICES, default='manual')
    marked_by      = models.ForeignKey(SystemUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_attendance_marked')
    notes          = models.TextField(blank=True)

    # ── Check-in / Check-out ──────────────────────────────────
    check_in_time  = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)

    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'date')
        ordering = ['-date', 'student__first_name']
        verbose_name = 'Student Attendance'
        verbose_name_plural = 'Student Attendance'

    def __str__(self):
        return f'{self.student.full_name} — {self.date} — {self.status}'
    
     
class ActivityLog(models.Model):
    TYPE_CHOICES=[
        ('admission','New Admission'),('renewal','Subscription Renewal'),
        ('payment','Payment Received'),('expiry_alert','Expiry Alert Sent'),
        ('status_change','Status Change'),('edit','Record Edited'),('delete','Record Deleted'),
    ]
    DOT_COLORS={
        'admission':'#3A7A52','renewal':'#2E6B9E','payment':'#C47A30',
        'expiry_alert':'#B84040','status_change':'#6A3DAA','edit':'#2E6B9E','delete':'#B84040',
    }
    activity_type=models.CharField(max_length=20,choices=TYPE_CHOICES)
    title=models.CharField(max_length=255)
    description=models.TextField(blank=True)
    student=models.ForeignKey(StudentData,on_delete=models.SET_NULL,null=True,blank=True,related_name='activity_logs')
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta: ordering=['-created_at']; verbose_name='Activity Log'; verbose_name_plural='Activity Logs'
    def __str__(self): return f'[{self.activity_type}] {self.title}'
    @property
    def dot_color(self): return self.DOT_COLORS.get(self.activity_type,'#8A8480')
    @property
    def time_ago(self):
        now=timezone.now(); delta=now-self.created_at; s=int(delta.total_seconds())
        if s<60: return 'Just now'
        if s<3600: return f'{s//60} min ago'
        if s<86400: return f'{s//3600} hr{"s" if s//3600>1 else ""} ago'
        if s<172800: return 'Yesterday'
        if s<604800: return f'{s//86400} days ago'
        return self.created_at.strftime('%d %b %Y')




class Payment(models.Model):
    """Individual payment transaction against a student's fee."""

    MODE_CHOICES = [
        ('cash',   'Cash'),
        ('upi',    'UPI'),
        ('online', 'Online Transfer'),
        ('cheque', 'Cheque'),
        ('other',  'Other'),
    ]

    student      = models.ForeignKey(
                       'StudentData', on_delete=models.CASCADE,
                       related_name='payments')
    amount       = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='cash')
    payment_date = models.DateField()
    reference    = models.CharField(max_length=100, blank=True,
                                    help_text='UTR / Cheque no. / Transaction ID')
    note         = models.TextField(blank=True)
    recorded_by  = models.ForeignKey(
                       'SystemUser', on_delete=models.SET_NULL,
                       null=True, blank=True, related_name='payments_recorded')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']
        verbose_name        = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return (f'{self.student.student_id} — ₹{self.amount} '
                f'via {self.payment_mode} on {self.payment_date}')

    @property
    def mode_display(self):
        return dict(self.MODE_CHOICES).get(self.payment_mode, self.payment_mode)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from decimal import Decimal
        from django.db.models import F, Case, When, Value, DecimalField
 
        StudentData.objects.filter(pk=self.student.pk).update(
            fee_paid=F('fee_paid') + self.amount,
            fee_due=Case(
                When(
                    fee_due__gte=self.amount,
                    then=F('fee_due') - self.amount
                ),
                default=Value(Decimal('0')),
                output_field=DecimalField(),
            )
        )


class SiteVisit(models.Model):
    visited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Site Visit"