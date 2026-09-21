from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def healthz(request):
    checks={"database":False,"cache":False}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"]=cursor.fetchone()==(1,)
    except Exception:
        checks["database"]=False

    try:
        cache.set("healthz","ok",10)
        checks["cache"]=cache.get("healthz")=="ok"
    except Exception:
        checks["cache"]=False

    healthy=all(checks.values())
    return JsonResponse(
        {"status":"ok" if healthy else "degraded","checks":checks},
        status=200 if healthy else 503,
    )


def home(request):
    return render(request,"home.html")
