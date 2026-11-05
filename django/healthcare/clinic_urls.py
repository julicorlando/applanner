from django.urls import path
from . import clinic_views as views
from . import assessment_views as assessments
from . import waiting_room, offline, rooms, document_views
from finance import clinic_views as finance
from communications.birthdays import configuration as birthday_configuration
urlpatterns=[
    path("financeiro/profissional/",finance.professional_report,name="clinic-professional-finance"),
    path('documentos/',document_views.documents,name='clinical-documents'),
    path('documentos/modelos/',document_views.templates,name='clinical-document-templates'),
    path('documentos/<int:pk>/',document_views.detail,name='clinical-document-detail'),
    path('documentos/<int:pk>/pdf/',document_views.pdf,name='clinical-document-pdf'),
    path('assinatura/',document_views.signature,name='clinical-signature'),
    path('assinatura/imagem/',document_views.signature_image,name='clinical-signature-image'),
    path("financeiro/aniversarios/",birthday_configuration,name="clinic-birthday-settings"),
    path('financeiro/',finance.desk,name='clinic-finance-desk'),
    path('financeiro/receber/<int:pk>/',finance.receive,name='clinic-finance-receive'),
    path('financeiro/comprovante/<int:pk>/',finance.photo,name='clinic-finance-photo'),
    path("operacao/snapshot/", offline.snapshot, name="clinical-offline-snapshot"),
    path("operacao/sincronizar/", offline.synchronize, name="clinical-offline-sync"),
    path("tv/sala/", rooms.select_room, name="waiting-room-select"),
    path("tv/salas/", rooms.manage_room, name="waiting-room-rooms"),
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
