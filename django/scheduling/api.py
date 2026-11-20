from datetime import date

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .availability import AvailabilityService


class AvailabilityAPIView(APIView):
    permission_classes=[permissions.IsAuthenticated]

    def get(self,request):
        tenant=getattr(request,"tenant",None)
        if tenant is None:
            return Response({"detail":"Tenant não identificado."},status=status.HTTP_403_FORBIDDEN)

        try:
            service_id=int(request.query_params["service_id"])
            professional_id=int(request.query_params["professional_id"])
            day=date.fromisoformat(request.query_params["date"])
        except (KeyError,TypeError,ValueError):
            return Response(
                {"detail":"Informe service_id, professional_id e date=YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slots=AvailabilityService().slots(
            tenant=tenant,
            service_id=service_id,
            professional_id=professional_id,
            day=day,
            public_rules=False,
        )
        return Response({"date":day.isoformat(),"slots":slots})
