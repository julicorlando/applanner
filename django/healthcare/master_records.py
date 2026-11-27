"""Master (platform) access to a clinic's patient records and bulk import of old sheets.

Every page view and import is written to the clinic's audit log; record reads also go to the
clinical access log, exactly as for the clinic team.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from accounts.models import User
from core.audit import append_audit
from core.master import _guard
from scheduling.models import Customer
from tenants.models import Tenant

from . import record_import
from .patient_record import build_timeline


def _company(request, pk):
    _guard(request.user)
    return get_object_or_404(Tenant, pk=pk, deleted_at__isnull=True)


def _owners(tenant):
    """Clinic users who can own imported patients (dentists first)."""
    rows = User.objects.filter(tenant=tenant, is_active=True, deleted_at__isnull=True)
    clinical = rows.filter(professional__active=True, professional__tenant=tenant).order_by("pk")
    return list(clinical) or list(rows.filter(role__in=["owner", "tenant-admin", "manager"]).order_by("pk"))


@login_required
@never_cache
def patients(request, pk):
    tenant = _company(request, pk)
    query = " ".join((request.GET.get("q") or "").split())
    rows = Customer.objects.filter(tenant=tenant).order_by("name")
    if query:
        digits = "".join(ch for ch in query if ch.isdigit())
        rows = rows.filter(Q(name__icontains=query) | (Q(phone__contains=digits) if len(digits) >= 4 else Q(pk__in=[])))
    page = Paginator(rows, 50).get_page(request.GET.get("pagina"))
    append_audit(tenant=tenant, user=request.user, request=request, action="master.patient_records.listed",
                 entity_type="Tenant", entity_id=tenant.pk, after={"query": bool(query)})
    return render(request, "master/patient_records.html", {"company": tenant, "page": page, "query": query})


@login_required
@never_cache
def patient(request, pk, customer_pk):
    tenant = _company(request, pk)
    row = get_object_or_404(Customer, tenant=tenant, pk=customer_pk)
    append_audit(tenant=tenant, user=request.user, request=request, action="master.patient_record.viewed",
                 entity_type="Customer", entity_id=row.pk)
    timeline = build_timeline(tenant=tenant, patient=row, user=request.user, ip=request.META.get("REMOTE_ADDR", ""), clinical=False)
    return render(request, "master/patient_record.html", {"company": tenant, "patient": row, "timeline": timeline})


@login_required
@never_cache
def import_sheets(request, pk):
    tenant = _company(request, pk)
    owners = _owners(tenant)
    chosen = request.POST.get("owner") or request.GET.get("owner")
    owner = next((u for u in owners if str(u.pk) == str(chosen)), owners[0] if owners else None)
    return record_import.handle(
        request, tenant,
        context={"base_template": "base.html", "company": tenant, "owners": owners, "owner_id": owner.pk if owner else None},
        done_url=reverse("master-patient-records", args=[tenant.pk]), owner=owner,
        again_url=reverse("master-record-import", args=[tenant.pk]))
