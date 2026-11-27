from django.conf import settings

def environment(request):
    return {"clinical_homologation":settings.DEPLOYMENT_ENVIRONMENT=="homologacao"}
