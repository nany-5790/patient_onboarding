# patients/models.py
import uuid
from django.db import models
from django.contrib.auth.models import User


class Patient(models.Model):
    """
    PHI — Personal Health Information separated from clinical data.
    """
    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('inactive', 'Inactive'),
                 ('pending', 'Pending')],
        default='pending',
        db_index=True,
    )
    assigned_doctor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='patients',
    )

    # PHI — en producción irían encriptados
    full_name = models.CharField(max_length=200)
    date_of_birth = models.DateField()
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        indexes = [
            # Índice parcial — solo pacientes activos
            models.Index(
                fields=['status', '-created_at'],
                name='idx_patients_status_created',
            )
        ]

    def __str__(self):
        return f"{self.full_name} ({self.status})"


class HealthRecord(models.Model):
    """
    Clinical data separated from patient profile.
    """
    patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        related_name='health_record',
    )
    insurance_provider = models.CharField(max_length=100, blank=True)
    insurance_id = models.CharField(max_length=50, blank=True)
    allergies = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"HealthRecord for {self.patient.full_name}"


class AuditLog(models.Model):
    """
    Inmutable — register each actions on patient data.
    """
    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    actor = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    actor_ip = models.GenericIPAddressField(null=True)
    # 'patient.created', 'patient.viewed'
    action = models.CharField(max_length=100)
    resource_type = models.CharField(
        max_length=100)  # 'Patient', 'HealthRecord'
    resource_id = models.UUIDField(null=True)
    extra = models.JSONField(default=dict)            # metadata adicional

    class Meta:
        indexes = [
            models.Index(fields=['resource_type', 'resource_id']),
            models.Index(fields=['actor', 'timestamp']),
        ]

    def save(self, *args, **kwargs):
        # Inmutabilidad — no permitir edits
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise PermissionError("Audit logs are immutable")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} by {self.actor} at {self.timestamp}"


class OnboardingRequest(models.Model):
    """
    Idempotency — prevent duplicate patient onboarding requests.
    """
    idempotency_key = models.UUIDField(unique=True, db_index=True)
    patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        related_name='onboarding_request',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OnboardingRequest {self.idempotency_key}"
