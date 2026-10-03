import re
from decimal import Decimal, InvalidOperation

import requests
from celery import shared_task
from django.utils import timezone

from .models import Unit


def _clean_cep(value):
    digits=re.sub(r"\D","",value or "")
    return digits if len(digits)==8 else ""


@shared_task(bind=True,max_retries=3,autoretry_for=(requests.RequestException,),retry_backoff=True)
def geocode_unit_from_postal_code(self,unit_id):
    unit=Unit.objects.filter(pk=unit_id,active=True).first()
    if not unit:
        return "missing"
    cep=_clean_cep(unit.postal_code)
    if not cep:
        return "invalid_cep"
    response=requests.get(f"https://brasilapi.com.br/api/cep/v2/{cep}",timeout=8)
    response.raise_for_status()
    data=response.json() if response.content else {}
    coords=((data.get("location") or {}).get("coordinates") or {})
    lat=coords.get("latitude")
    lon=coords.get("longitude")
    updates={}
    try:
        if lat not in (None,"") and lon not in (None,""):
            updates["latitude"]=Decimal(str(lat))
            updates["longitude"]=Decimal(str(lon))
            updates["geocoded_at"]=timezone.now()
    except (InvalidOperation,TypeError,ValueError):
        pass
    mapping={
        "street":"address",
        "neighborhood":"district",
        "city":"city",
        "state":"state",
    }
    for source,target in mapping.items():
        if not getattr(unit,target) and data.get(source):
            updates[target]=str(data[source])[:Unit._meta.get_field(target).max_length]
    if updates:
        Unit.objects.filter(pk=unit.pk).update(**updates,updated_at=timezone.now())
        return "updated"
    return "no_coordinates"
