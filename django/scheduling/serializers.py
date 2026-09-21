from rest_framework import serializers
from .models import Appointment


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model=Appointment
        fields=["id","customer","professional","service","starts_at","ends_at","status","source","notes"]
        read_only_fields=["id"]
