import uuid
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from patients.models import Patient
from appointments.models import Appointment, Provider, AppointmentStatus
from appointments.exceptions import DoubleBookingError


def make_provider():
    return Provider.objects.create(name="Dr. House", specialty="Diagnostics")


def make_patient():
    return Patient.objects.create(
        full_name="Test Patient",
        date_of_birth="1990-01-01",
        email=f"{uuid.uuid4()}@test.com",
    )


def base_times():
    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(hours=1)
    return start, end


class AppointmentIdempotencyTest(TestCase):
    def setUp(self):
        self.provider = make_provider()
        self.patient = make_patient()
        self.start, self.end = base_times()
        self.key = uuid.uuid4()

    def _book(self, key=None):
        return Appointment.objects.book(
            patient_id=self.patient.pk,
            provider_id=self.provider.pk,
            start_time=self.start,
            end_time=self.end,
            appointment_type="consultation",
            idempotency_key=key or self.key,
        )

    def test_same_key_returns_same_appointment(self):
        a1 = self._book()
        a2 = self._book()
        self.assertEqual(a1.pk, a2.pk)

    def test_same_key_does_not_create_duplicate(self):
        self._book()
        self._book()
        self.assertEqual(Appointment.objects.filter(idempotency_key=self.key).count(), 1)

    def test_different_keys_create_different_appointments(self):
        start2 = self.end + timedelta(hours=1)
        end2 = start2 + timedelta(hours=1)
        a1 = self._book(key=uuid.uuid4())
        a2 = Appointment.objects.book(
            patient_id=self.patient.pk,
            provider_id=self.provider.pk,
            start_time=start2,
            end_time=end2,
            appointment_type="consultation",
            idempotency_key=uuid.uuid4(),
        )
        self.assertNotEqual(a1.pk, a2.pk)

    def test_overlapping_slot_raises_double_booking(self):
        self._book(key=uuid.uuid4())
        with self.assertRaises(DoubleBookingError):
            self._book(key=uuid.uuid4())
