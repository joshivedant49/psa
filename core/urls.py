from django.urls import path
from . import views

urlpatterns = [
    # path('', views.home,name='home'),
    path('sportsacademy/',views.home,name='home'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/notify-all/', views.notify_all, name='notify_all'),
    # ── Auth ───────────────────────────────────────────────────────────
    path('',                              views.login_view,             name='login'),
    path('logout/',                             views.logout_view,            name='logout'),
    # ── Masters: Sports ────────────────────────────────────
    path('masters/sports/',            views.sports_master,       name='sports_master'),
    path('masters/sports/<int:pk>/edit/',   views.sport_edit,     name='sport_edit'),
    path('masters/sports/<int:pk>/delete/', views.sport_delete,   name='sport_delete'),
    path('masters/sports/<int:pk>/toggle/', views.sport_toggle_status, name='sport_toggle'),
    # ── Masters : Batch ────────────────────────────────────────────────
    path('masters/batches/',                        views.batch_master,           name='batch_master'),
    path('masters/batches/<int:pk>/edit/',          views.batch_edit,             name='batch_edit'),
    path('masters/batches/<int:pk>/delete/',        views.batch_delete,           name='batch_delete'),
    path('masters/batches/<int:pk>/toggle/',        views.batch_toggle_status,    name='batch_toggle'),
    # ── Masters : Expertise Level ──────────────────────────────────────
    path('masters/expertise-levels/',               views.expertise_level_master, name='expertise_level_master'),
    path('masters/expertise-levels/<int:pk>/edit/', views.expertise_level_edit,   name='expertise_level_edit'),
    path('masters/expertise-levels/<int:pk>/delete/',views.expertise_level_delete,name='expertise_level_delete'),
    path('masters/expertise-levels/<int:pk>/toggle/',views.expertise_level_toggle,name='expertise_level_toggle'),
    # ___ Masters : Duration Master ___________________________________________________
    path('masters/duration/',            views.duration_master,       name='duration_master'),
    path('masters/duration/<int:pk>/edit/',   views.duration_edit,     name='duration_edit'),
    path('masters/duration/<int:pk>/delete/', views.duration_delete,   name='duration_delete'),
    path('masters/duration/<int:pk>/toggle/', views.duration_toggle_status, name='duration_toggle'),
    # ── Masters : Fee Structure ────────────────────────────────────────
    path('masters/fees/',                           views.fee_structure,        name='fee_structure'),
    path('masters/fees/<int:pk>/edit/',             views.fee_structure_edit,   name='fee_structure_edit'),
    path('masters/fees/<int:pk>/delete/',           views.fee_structure_delete, name='fee_structure_delete'),
    path('masters/fees/<int:pk>/toggle/',           views.fee_structure_toggle, name='fee_structure_toggle'),
    # ── Students ────────────────────────────────────────────────────────
    path('students/admission/',                views.student_admission, name='student_admission'),
    path('students/admission/<int:pk>/success/',views.admission_success, name='admission_success'),
    path('students/get-fee/',                  views.get_fee,           name='get_fee'),
    # ── Student List ────────────────────────────────────────────────────
    path('students/',                          views.student_list,      name='student_list'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    # ── User Management (admin only) ───────────────────────────────────
    path('users/',                              views.user_list,              name='user_list'),
    path('users/create/',                       views.user_create,            name='user_create'),
    path('users/<int:pk>/permissions/',         views.user_permissions,       name='user_permissions'),
    path('users/<int:pk>/reset-password/',      views.user_reset_password,    name='user_reset_password'),
    path('users/<int:pk>/toggle/',              views.user_toggle,            name='user_toggle'),
    # ── Attendance ─────────────────────────────────────────────────────
    path('attendance/coaches/',                 views.coach_attendance,       name='coach_attendance'),
    path('attendance/coaches/history/',         views.coach_attendance_history,   name='coach_attendance_history'),
    path('attendance/students/history/',        views.student_attendance_history, name='student_attendance_history'),
    path('attendance/students/',                views.student_attendance,     name='student_attendance'),
    path('attendance/qr/',                      views.qr_scan_page,           name='qr_scan'),
    path('attendance/qr-mark/',                 views.qr_mark_attendance,     name='qr_mark_attendance'),
    path('attendance/coaches/history/export/',  views.coach_attendance_history_export,   name='coach_attendance_history_export'),
    path('attendance/students/history/export/', views.student_attendance_history_export,  name='student_attendance_history_export'),
    # ── Coaches ────────────────────────────────────────────────────────
    path('coaches/',                            views.coach_list,             name='coach_list'),
    path('coaches/add/',                        views.coach_add,              name='coach_add'),
    path('coaches/<int:pk>/',                   views.coach_detail,           name='coach_detail'),
    path('coaches/<int:pk>/edit/',              views.coach_edit,             name='coach_edit'),
    path('coaches/<int:pk>/delete/',            views.coach_delete,           name='coach_delete'),
    path('coaches/<int:pk>/toggle/',            views.coach_toggle_status,    name='coach_toggle'),
    path('reports/',       views.reports_page, name='reports'),
    path('reports/pdf/',   views.report_pdf,   name='report_pdf'),
    path('reports/count/', views.report_count, name='report_count'),
    path('payments/', views.student_payment_history, name='payment_records'),
    path('payments/record/', views.record_payment, name='record_payment'),
    path('payments/history/<int:pk>/', views.payment_history, name='payment_history'),
    path('attendance/dashboard/', views.attendance_dashboard, name='attendance_dashboard'),
    path('students/<int:pk>/renew/', views.student_renew, name='student_renew'),

]