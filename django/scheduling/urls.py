from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import AvailabilityAPIView
from .views import AppointmentViewSet

router=DefaultRouter()
router.register("appointments",AppointmentViewSet,basename="appointment")

urlpatterns=[
    path("availability/",AvailabilityAPIView.as_view(),name="availability"),
]
urlpatterns += router.urls
