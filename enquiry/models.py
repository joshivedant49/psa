from django.db import models


class Enquiry(models.Model):
    STATUS_CHOICES = [
        ('new',        'New'),
        ('contacted',  'Contacted'),
        ('enrolled',   'Enrolled'),
        ('closed',     'Closed'),
    ]

    # Form fields
    full_name   = models.CharField(max_length=150)
    phone       = models.CharField(max_length=20)
    email       = models.EmailField(blank=True)
    sport       = models.CharField(max_length=100, blank=True)
    age         = models.PositiveSmallIntegerField(null=True, blank=True)
    message     = models.TextField(blank=True)

    # Meta
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    whatsapp_sent = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Enquiry'
        verbose_name_plural = 'Enquiries'

    def __str__(self):
        return f"{self.full_name} — {self.sport} ({self.created_at.strftime('%d %b %Y')})"
