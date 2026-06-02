import uuid
from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth.models import User
from appointments.exceptions import DoubleBookingError, InvalidTransitionError


class AppointmentStatus(models.TextChoices):
    CONFIRMED = 'confirmed', 'Confirmed'
    COMPLETED = 'completed', 'Completed'
    CANCELED = 'canceled', 'Canceled'
    PENDING = 'pending', 'Pending'
    NO_SHOW = 'no_show', 'No Show'


# Valid Transitions map. wich status can be followed by which status
VALID_TRANSITIONS = {
    AppointmentStatus.PENDING: [AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELED],
    AppointmentStatus.CONFIRMED: [AppointmentStatus.COMPLETED, AppointmentStatus.CANCELED, AppointmentStatus.NO_SHOW],
    AppointmentStatus. CANCELED: set(),
    AppointmentStatus.COMPLETED: set(),
    AppointmentStatus.NO_SHOW: set(),
}


class Provider(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    specialty = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Provider'
        verbose_name_plural = 'Providers'
        db_table = 'providers'


class AppointmentManager(models.Manager):
    def book(self, patient_id, provider_id, start_time, end_time,
             appointment_type, idempotency_key):

        # 1. Idempotency check —if key existes, return existing appointment
        existing = self.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        with transaction.atomic():
            # 2. Lock the provider — no other thread can read its appointments until this transaction finishes
            # 2. Lockea el proveedor — ningún otro thread puede leer sus appointments hasta que esta transacción termine
            Provider.objects.select_for_update().get(pk=provider_id)

            #  3. Search for overlaps — the formula is: start_existing < end_new AND end_existing > start_new
            #  3. Busca overlaps — la fórmula es: start_existente < end_nuevo  AND  end_existente > start_nuevo
            overlap = self.filter(
                provider_id=provider_id,
                status__in=[AppointmentStatus.PENDING,
                            AppointmentStatus.CONFIRMED],
                start_time__lt=end_time,
                end_time__gt=start_time,
            ).select_for_update().exists()

            if overlap:
                raise DoubleBookingError(
                    f"Provider {provider_id} is not available from {start_time} to {end_time}."
                )

            return self.create(
                patient_id=patient_id,
                provider_id=provider_id,
                start_time=start_time,
                end_time=end_time,
                appointment_type=appointment_type,
                idempotency_key=idempotency_key,
                status=AppointmentStatus.PENDING,
            )

    def transition(self, appointment_id, new_status):
        with transaction.atomic():
            appt = self.select_for_update().get(pk=appointment_id)
            allowed = VALID_TRANSITIONS.get(appt.status, set())
            if new_status not in allowed:
                raise InvalidTransitionError(
                    f"Cannot transition from '{appt.status}' to '{new_status}'."
                )
            appt.status = new_status
            appt.updated_at = timezone.now()
            appt.save(update_fields=["status", "updated_at"])
            return appt


class Appointment(models.Model):
    # Foreign keys to model Patient
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name='appointments')
    provider = models.ForeignKey(
        Provider, on_delete=models.PROTECT, related_name='appointments')
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField(db_index=True)
    appointment_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=AppointmentStatus.choices,
                              default=AppointmentStatus.PENDING, db_index=True)

    # Client generate this uuid to ensure idempotency.
    # If the same key is used again, the system will return the existing appointment instead of creating a new one.
    idempotency_key = models.UUIDField(unique=True, default=uuid.uuid4)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AppointmentManager()

    class Meta:
        verbose_name = 'Appointment'
        verbose_name_plural = 'Appointments'
        db_table = 'appointments'
        indexes = [
            # Composite index to speed up overlap queries
            # Índice compuesto para acelerar las queries de overlap
            models.Index(fields=['provider', 'start_time',
                         'end_time'], name='idx_provider_time_range'),
        ]
