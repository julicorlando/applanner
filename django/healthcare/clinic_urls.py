from django.urls import path
from . import clinic_views as views
urlpatterns=[
    path("",views.dashboard,name="clinical-dashboard"),
    path("registro-profissional/",views.registration,name="clinical-registration"),
    path("novo/<str:kind>/",views.structured_record,name="clinical-structured"),
    path("registro/<int:pk>/",views.record_detail,name="clinical-record"),
    path("documento/<int:pk>/",views.attachment_download,name="clinical-attachment"),
    path("paciente/<int:pk>/",views.patient,name="clinical-patient"),
    path("paciente/<int:pk>/exportar/<str:kind>/",views.export_patient,name="clinical-export"),
]
