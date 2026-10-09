from rest_framework import permissions,viewsets
from accounts.permissions import has_capability
from .models import Appointment
from .serializers import AppointmentSerializer


class ManageAppointmentsPermission(permissions.BasePermission):
    """The operational API is for agenda managers; professionals use their own area."""
    def has_permission(self,request,view):
        user=request.user
        return bool(user and user.is_authenticated and
            (user.is_superuser or user.role!="professional") and
            has_capability(user,"agenda.manage"))


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class=AppointmentSerializer
    permission_classes=[ManageAppointmentsPermission]

    def get_queryset(self):
        tenant=getattr(self.request,"tenant",None)
        if tenant is None:
            return Appointment.objects.none()
        return Appointment.objects.filter(tenant=tenant).select_related("customer","professional","service").order_by("starts_at")

    def perform_create(self,serializer):
        serializer.save(tenant=self.request.tenant,created_by=self.request.user)
