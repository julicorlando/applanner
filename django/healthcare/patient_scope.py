"""Clinical patient lists follow actual assignments, never the platform role."""
from django.db.models import Q
from scheduling.models import Customer


def patients_for(user, *, administrative=False):
    if not user or not user.is_authenticated or not user.tenant_id or user.is_superuser:
        return Customer.objects.none()
    rows=Customer.objects.filter(tenant_id=user.tenant_id)
    if administrative and user.role in {'owner','tenant-admin','manager','reception','finance'}:
        return rows
    return rows.filter(Q(registered_by=user)|Q(appointments__professional__user=user,appointments__professional__active=True)
        |Q(medical_records__professional__user=user,medical_records__professional__active=True)
        |Q(clinical_documents__professional__user=user,clinical_documents__professional__active=True)).distinct()
