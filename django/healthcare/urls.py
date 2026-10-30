from django.urls import path
from . import views, dental_assessment_views as assessments

urlpatterns = [
    path("prontuarios/", assessments.assessment_list, name="dental-assessments"),
    path("prontuarios/novo/", assessments.assessment_editor, name="dental-assessment-create"),
    path("prontuarios/<int:pk>/", assessments.assessment_editor, name="dental-assessment-detail"),
    path("prontuarios/paciente/<int:pk>/opcoes/", assessments.patient_options, name="dental-assessment-patient-options"),
    path("prontuarios/documento/<int:pk>/", assessments.assessment_document, name="dental-assessment-document"),
    path("paciente/<int:customer_id>/odontograma/",views.dental_chart,name="dental-chart"),
    path("", views.dental_home, name="dental-home"),
    path("evolucao/nova/", views.dental_encounter, name="dental-encounter"),
    path("paciente/<int:customer_id>/", views.dental_patient, name="dental-patient"),
]
