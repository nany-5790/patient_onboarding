from rest_framework import serializers
from .models import Patient, HealthRecord
import uuid


class HealthRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = HealthRecord
        fields = ['insurance_provider', 'insurance_id', 'allergies', 'notes']


class PatientOnboardingSerializer(serializers.ModelSerializer):
    health_record = HealthRecordSerializer()
    idempotency_key = serializers.UUIDField(default=uuid.uuid4)

    class Meta:
        model = Patient
        fields = [
            'full_name', 'date_of_birth', 'email',
            'phone', 'health_record', 'idempotency_key',
        ]

    def validate_idempotency_key(self, value):
        from .models import OnboardingRequest
        if OnboardingRequest.objects.filter(idempotency_key=value).exists():
            raise serializers.ValidationError("duplicate_request")
        return value

    def create(self, validated_data):
        from django.db import transaction
        from .models import OnboardingRequest

        health_data = validated_data.pop('health_record')
        idempotency_key = validated_data.pop('idempotency_key')

        with transaction.atomic():
            patient = Patient.objects.create(**validated_data)
            HealthRecord.objects.create(patient=patient, **health_data)
            OnboardingRequest.objects.create(
                idempotency_key=idempotency_key,
                patient=patient,
            )
        return patient
