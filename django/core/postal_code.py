import requests
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from tenants.address_lookup import PostalCodeNotFound, lookup_postal_code


@login_required
@require_GET
def postal_code_lookup(request):
    # Bound third-party traffic per signed-in account; successful CEP results are shared in cache.
    key=f"unit-cep-rate:{request.user.pk}"
    cache.add(key,0,timeout=60)
    if cache.incr(key)>30:
        return JsonResponse({"error":"Muitas consultas. Aguarde um minuto e tente novamente."},status=429)
    try:
        return JsonResponse(lookup_postal_code(request.GET.get("cep","")))
    except PostalCodeNotFound as exc:
        return JsonResponse({"error":str(exc)},status=404)
    except ValueError as exc:
        return JsonResponse({"error":str(exc)},status=400)
    except requests.RequestException:
        return JsonResponse({"error":"Consulta de CEP indisponível. Tente novamente ou preencha o endereço manualmente."},status=503)
