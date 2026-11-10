"""Cached CEP lookup and optional street-number geocoding for unit addresses."""
import hashlib
import re
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache


class PostalCodeNotFound(ValueError):
    pass


def clean_cep(value):
    text=str(value or "").strip()
    return re.sub(r"\D", "", text) if re.fullmatch(r"\d{5}-?\d{3}", text) else ""


def coordinates(latitude, longitude):
    try:
        lat,lon=Decimal(str(latitude)),Decimal(str(longitude))
        if lat.is_finite() and lon.is_finite() and -90<=lat<=90 and -180<=lon<=180:
            return lat.quantize(Decimal("0.0000001")),lon.quantize(Decimal("0.0000001"))
    except (InvalidOperation, TypeError, ValueError):
        pass
    return None


def lookup_postal_code(value):
    cep=clean_cep(value)
    if not cep:
        raise ValueError("Informe um CEP válido com 8 dígitos.")
    key=f"unit-cep:v1:{cep}"
    cached=cache.get(key)
    if cached is not None:
        return cached
    try:
        response=requests.get(f"https://brasilapi.com.br/api/cep/v2/{cep}",timeout=6)
        response.raise_for_status()
        raw=response.json()
        if not isinstance(raw,dict) or not raw.get("city"):
            raise ValueError("Resposta inválida da consulta de CEP.")
        location=raw.get("location") or {}
        coords=location.get("coordinates") or {}
        pair=coordinates(coords.get("latitude"),coords.get("longitude"))
        data={"postal_code":cep,"address":raw.get("street") or "", "district":raw.get("neighborhood") or "",
              "city":raw["city"],"state":raw.get("state") or "",
              "latitude":str(pair[0]) if pair else None,"longitude":str(pair[1]) if pair else None}
    except (requests.RequestException,ValueError,TypeError,AttributeError):
        response=requests.get(f"https://viacep.com.br/ws/{cep}/json/",timeout=6)
        response.raise_for_status()
        raw=response.json()
        if not isinstance(raw,dict) or raw.get("erro") or not raw.get("localidade"):
            raise PostalCodeNotFound("CEP não encontrado. Confira os números ou preencha o endereço manualmente.")
        data={"postal_code":cep,"address":raw.get("logradouro") or "", "district":raw.get("bairro") or "",
              "city":raw["localidade"],"state":raw.get("uf") or "","latitude":None,"longitude":None}
    cache.set(key,data,86400)
    return data


def geocode_address(unit, address):
    """Search only on save, never as autocomplete; cache and limit all workers to 1 request/s."""
    if not address.get("address") or not unit.address_number or not address.get("city"):
        return None
    endpoint=getattr(settings,"UNIT_GEOCODING_URL","https://nominatim.openstreetmap.org/search")
    params={"street":f"{unit.address_number} {address['address']}","city":address["city"],
            "state":address.get("state", ""),"postalcode":clean_cep(unit.postal_code),
            "countrycodes":"br","format":"jsonv2","limit":1}
    key="unit-geocode:v1:"+hashlib.sha256(repr((endpoint,sorted(params.items()))).encode()).hexdigest()
    cached=cache.get(key)
    if cached is not None:
        return tuple(Decimal(item) for item in cached) if cached else None
    if not cache.add("unit-geocode:rate-limit",True,timeout=1):
        raise requests.RequestException("Geocodificador ocupado; tentar novamente.")
    response=requests.get(endpoint,params=params,headers={"User-Agent":"ApPlanner/1.0 (+https://applanner.com.br)","Accept-Language":"pt-BR"},timeout=8)
    response.raise_for_status()
    rows=response.json()
    pair=coordinates(rows[0].get("lat"),rows[0].get("lon")) if isinstance(rows,list) and rows and isinstance(rows[0],dict) else None
    cache.set(key,[str(x) for x in pair] if pair else [],86400)
    return pair
