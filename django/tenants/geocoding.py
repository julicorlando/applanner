import re

import requests
from django.core.cache import cache
from django.utils import timezone


def normalize_postal_code(value):
    digits=re.sub(r"\D","",value or "")
    return digits if len(digits)==8 else ""


def postal_code_location(postal_code):
    cep=normalize_postal_code(postal_code)
    if not cep:
        return None
    key=f"postal-location:{cep}"
    cached=cache.get(key)
    if cached is not None:
        return cached
    try:
        response=requests.get(f"https://viacep.com.br/ws/{cep}/json/",timeout=2.0)
        response.raise_for_status()
        data=response.json()
        if data.get("erro"):
            cache.set(key,{},3600)
            return None
        result={
            "postal_code":cep,
            "address":str(data.get("logradouro") or "")[:255],
            "district":str(data.get("bairro") or "")[:100],
            "city":str(data.get("localidade") or "")[:100],
            "state":str(data.get("uf") or "")[:2].upper(),
        }
        cache.set(key,result,60*60*24*30)
        return result
    except (requests.RequestException,ValueError,TypeError):
        return None


def coordinates_for_postal_code(postal_code):
    cep=normalize_postal_code(postal_code)
    if not cep:
        return None
    key=f"postal-coordinates:{cep}"
    cached=cache.get(key)
    if cached is not None:
        return tuple(cached) if cached else None
    location=postal_code_location(cep)
    if not location:
        return None
    query=", ".join(filter(None,[
        location.get("address"),location.get("district"),
        location.get("city"),location.get("state"),cep,"Brasil",
    ]))
    try:
        response=requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q":query,"format":"jsonv2","limit":1,"countrycodes":"br"},
            headers={"User-Agent":"ApPlanner/1.0 (geocoding de unidades cadastradas)"},
            timeout=2.5,
        )
        response.raise_for_status()
        rows=response.json()
        if not rows:
            cache.set(key,[],3600)
            return None
        coords=(float(rows[0]["lat"]),float(rows[0]["lon"]))
        cache.set(key,list(coords),60*60*24*30)
        return coords
    except (requests.RequestException,ValueError,TypeError,KeyError):
        return None


def enrich_unit_from_postal_code(unit,save=True):
    location=postal_code_location(unit.postal_code)
    if location:
        for field in ("address","district","city","state"):
            if not getattr(unit,field,None) and location.get(field):
                setattr(unit,field,location[field])
    coords=coordinates_for_postal_code(unit.postal_code)
    if coords:
        unit.latitude,unit.longitude=coords
        unit.geocoded_at=timezone.now()
    if save:
        unit.save(update_fields=[
            "postal_code","address","district","city","state",
            "latitude","longitude","geocoded_at","updated_at",
        ])
    return unit
