from django.urls import path
from . import views
# from .views import enquiry_dashboard, enquiry_bulk_action

urlpatterns = [
    path('enquiry/submit/', views.submit_enquiry, name='submit_enquiry'),
    path('dashboard/enquiries/',        views.enquiry_dashboard,    name='enquiry_dashboard'),
    path('dashboard/enquiries/bulk/',   views.enquiry_bulk_action,  name='enquiry_bulk_action'),
]
