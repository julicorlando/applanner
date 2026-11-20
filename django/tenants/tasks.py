import requests
from celery import shared_task
from django.utils import timezone

from .address_lookup import PostalCodeNotFound, clean_cep, coordinates, geocode_address, lookup_postal_code
from .models import Unit


_clean_cep=clean_cep


@shared_task(bind=True,max_retries=3,autoretry_for=(requests.RequestException,),retry_backoff=True)
def geocode_unit_from_postal_code(self,unit_id):
    unit=Unit.objects.filter(pk=unit_id,active=True).first()
    if not unit:
        return "missing"
    if not clean_cep(unit.postal_code):
        return "invalid_cep"
    try:
        data=lookup_postal_code(unit.postal_code)
    except PostalCodeNotFound:
        return "invalid_cep"
    fields=("postal_code","address","address_number","district","city","state","latitude","longitude")
    snapshot={field:getattr(unit,field) for field in fields}
    updates={}
    for field in ("address","district","city","state"):
        if not getattr(unit,field) and data.get(field):
            updates[field]=str(data[field])[:Unit._meta.get_field(field).max_length]
    address={field:updates.get(field,getattr(unit,field)) for field in ("address","district","city","state")}
    fallback=coordinates(data.get("latitude"),data.get("longitude"))
    try:
        pair=geocode_address(unit,address) or fallback
    except requests.RequestException:
        if not fallback:
            raise
        pair=fallback
    if pair:
        updates.update(latitude=pair[0],longitude=pair[1],geocoded_at=timezone.now())
    if updates:
        # An old worker must never overwrite coordinates or an address edited while the API was running.
        changed=Unit.objects.filter(pk=unit.pk,active=True,**snapshot).update(**updates,updated_at=timezone.now())
        return "updated" if changed else "stale"
    return "no_coordinates"


def queue_unit_geocoding(unit_id):
    """Schedule resolution after commit without blocking a saved unit."""
    try:
        geocode_unit_from_postal_code.delay(unit_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Não foi possível enfileirar a localização da unidade %s",unit_id)
