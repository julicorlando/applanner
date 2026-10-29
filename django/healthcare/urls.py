from django.urls import path
from . import views

urlpatterns = [
    path("paciente/<int:customer_id>/odontograma/",views.dental_chart,name="dental-chart"),
    path("", views.dental_home, name="dental-home"),
    path("evolucao/nova/", views.dental_encounter, name="dental-encounter"),
    path("paciente/<int:customer_id>/", views.dental_patient, name="dental-patient"),
]
