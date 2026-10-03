from rest_framework import permissions,viewsets
from .models import Appointment
from .serializers import AppointmentSerializer


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class=AppointmentSerializer
    permission_classes=[permissions.IsAuthenticated]

    def get_queryset(self):
        tenant=getattr(self.request,"tenant",None)
        if tenant is None:
            return Appointment.objects.none()
        return Appointment.objects.filter(tenant=tenant).select_related("customer","professional","service").order_by("starts_at")

    def perform_create(self,serializer):
        serializer.save(tenant=self.request.tenant,created_by=self.request.user)
