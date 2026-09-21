from django.db import transaction
from rest_framework import serializers

from .availability import AvailabilityService
from .models import Appointment, Professional


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model=Appointment
        fields=[
            "id","customer","professional","service",
            "starts_at","ends_at","status","source","notes",
        ]
        read_only_fields=["id"]

    def validate(self,attrs):
        request=self.context.get("request")
        tenant=getattr(request,"tenant",None)
        if tenant is None:
            raise serializers.ValidationError("Tenant não identificado.")

        starts_at=attrs.get("starts_at",getattr(self.instance,"starts_at",None))
        ends_at=attrs.get("ends_at",getattr(self.instance,"ends_at",None))
        if starts_at and ends_at and ends_at<=starts_at:
            raise serializers.ValidationError({"ends_at":"O término deve ser posterior ao início."})

        for field in ("customer","professional","service"):
            obj=attrs.get(field,getattr(self.instance,field,None))
            if obj is not None and obj.tenant_id!=tenant.id:
                raise serializers.ValidationError({field:"Registro não pertence ao estabelecimento autenticado."})
        return attrs

    def _save_with_availability_check(self,validated_data,instance=None):
        tenant=validated_data.get("tenant") or getattr(instance,"tenant",None)
        professional=validated_data.get("professional",getattr(instance,"professional",None))
        starts_at=validated_data.get("starts_at",getattr(instance,"starts_at",None))
        ends_at=validated_data.get("ends_at",getattr(instance,"ends_at",None))
        service=validated_data.get("service",getattr(instance,"service",None))

        with transaction.atomic():
            if professional is not None:
                professional=Professional.objects.select_for_update().get(
                    pk=professional.pk,
                    tenant=tenant,
                )
                if not AvailabilityService().professional_offers(
                    tenant,professional.pk,service.pk
                ):
                    raise serializers.ValidationError({
                        "professional":"O profissional não oferece este serviço."
                    })
                if not AvailabilityService().is_available(
                    tenant,
                    professional,
                    starts_at,
                    ends_at,
                    exclude_appointment_id=getattr(instance,"pk",None),
                    public_rules=False,
                ):
                    raise serializers.ValidationError({
                        "starts_at":"O profissional não está disponível nesse intervalo."
                    })

            if instance is None:
                return Appointment.objects.create(**validated_data)

            for key,value in validated_data.items():
                setattr(instance,key,value)
            instance.full_clean()
            instance.save()
            return instance

    def create(self,validated_data):
        return self._save_with_availability_check(validated_data)

    def update(self,instance,validated_data):
        return self._save_with_availability_check(validated_data,instance=instance)
