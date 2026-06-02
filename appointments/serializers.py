from rest_framework import serializers
from appointments.models import Appointment, Provider, AppointmentStatus


class AppointmentCreateSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    provider_id = serializers.IntegerField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    appointment_type = serializers.CharField(max_length=100)
    idempotency_key = serializers.UUIDField()

    def validate(self, data):
        if data["end_time"] <= data["start_time"]:
            raise serializers.ValidationError(
                {"end_time": "end_time debe ser posterior a start_time."}
            )
        return data


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = ["id", "patient", "provider", "start_time", "end_time",
                  "appointment_type", "status", "idempotency_key", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


class TransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=AppointmentStatus.choices)
