from django.urls import path
from . import clinic_views as views
from . import assessment_views as assessments
from . import waiting_room, offline
urlpatterns=[
    path("operacao/snapshot/", offline.snapshot, name="clinical-offline-snapshot"),
    path("operacao/sincronizar/", offline.synchronize, name="clinical-offline-sync"),
    path("tv/", waiting_room.console, name="waiting-room-console"),
    path("tv/chamar/", waiting_room.call_patient, name="waiting-room-call"),
    path("fisioterapia/",assessments.assessment_list,name="physio-assessments"),
    path("fisioterapia/avaliacao/nova/",assessments.assessment_editor,name="physio-assessment-create"),
    path("fisioterapia/avaliacao/<int:pk>/",assessments.assessment_editor,name="physio-assessment-detail"),
    path("fisioterapia/paciente/<int:pk>/opcoes/",assessments.patient_options,name="physio-patient-options"),
    path("fisioterapia/documento/<int:pk>/",assessments.assessment_document,name="physio-assessment-document"),
    path("",views.dashboard,name="clinical-dashboard"),
    path("registro-profissional/",views.registration,name="clinical-registration"),
    path("novo/<str:kind>/",views.structured_record,name="clinical-structured"),
    path("registro/<int:pk>/",views.record_detail,name="clinical-record"),
    path("documento/<int:pk>/",views.attachment_download,name="clinical-attachment"),
    path("paciente/<int:pk>/",views.patient,name="clinical-patient"),
    path("paciente/<int:pk>/exportar/<str:kind>/",views.export_patient,name="clinical-export"),
]
