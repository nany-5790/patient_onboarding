import uuid
import time
import threading
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from patients.models import Patient
from appointments.models import Appointment, Provider, AppointmentStatus
from appointments.exceptions import DoubleBookingError, InvalidTransitionError
from core.resilience import RetryWithBackoff, CircuitBreaker, CircuitBreakerOpen


# ── Helpers ────────────────────────────────────────────────────────────────

def make_provider(name="Dr. Smith"):
    return Provider.objects.create(name=name, specialty="General", is_active=True)


def make_patient():
    return Patient.objects.create(
        full_name="Test Patient",
        date_of_birth="1990-01-01",
        email=f"{uuid.uuid4()}@test.com",
    )


def slot(offset_hours=1, duration_minutes=30):
    start = timezone.now() + timedelta(hours=offset_hours)
    return start, start + timedelta(minutes=duration_minutes)


def book(provider, start, end, key=None, patient=None):
    if patient is None:
        patient = make_patient()
    return Appointment.objects.book(
        patient_id=patient.id, provider_id=provider.id,
        start_time=start, end_time=end,
        appointment_type="consultation",
        idempotency_key=key or str(uuid.uuid4()),
    )


# ── 1. Double booking ──────────────────────────────────────────────────────

class DoubleBookingTest(TestCase):
    def setUp(self):
        self.p = make_provider()

    def test_exact_overlap_blocked(self):
        start, end = slot(1)
        book(self.p, start, end)
        with self.assertRaises(DoubleBookingError):
            book(self.p, start, end)

    def test_partial_overlap_blocked(self):
        start, end = slot(1, 60)
        book(self.p, start, end)
        overlap_start = start + timedelta(minutes=30)
        with self.assertRaises(DoubleBookingError):
            book(self.p, overlap_start, overlap_start + timedelta(minutes=30))

    def test_adjacent_slot_allowed(self):
        start, end = slot(1, 30)
        book(self.p, start, end)
        # Empieza exactamente cuando termina el anterior
        result = book(self.p, end, end + timedelta(minutes=30))
        self.assertIsNotNone(result.pk)

    def test_cancelled_slot_is_available(self):
        start, end = slot(2)
        appt = book(self.p, start, end)
        Appointment.objects.transition(appt.id, AppointmentStatus.CANCELED)
        new = book(self.p, start, end)
        self.assertEqual(new.status, AppointmentStatus.PENDING)


# ── 2. Idempotency ─────────────────────────────────────────────────────────

class IdempotencyTest(TestCase):
    def setUp(self):
        self.p = make_provider()

    def test_same_key_returns_same_appointment(self):
        start, end = slot(1)
        key = str(uuid.uuid4())
        a1 = book(self.p, start, end, key=key)
        a2 = book(self.p, start, end, key=key)  # retry simulado
        self.assertEqual(a1.id, a2.id)
        self.assertEqual(Appointment.objects.filter(
            idempotency_key=key).count(), 1)


# ── 3. State machine ───────────────────────────────────────────────────────

class StateMachineTest(TestCase):
    def setUp(self):
        self.p = make_provider()
        start, end = slot(1)
        self.appt = book(self.p, start, end)

    def test_pending_to_confirmed(self):
        a = Appointment.objects.transition(
            self.appt.id, AppointmentStatus.CONFIRMED)
        self.assertEqual(a.status, AppointmentStatus.CONFIRMED)

    def test_invalid_transition_raises(self):
        with self.assertRaises(InvalidTransitionError):
            Appointment.objects.transition(
                self.appt.id, AppointmentStatus.COMPLETED)

    def test_terminal_state_blocks_all(self):
        Appointment.objects.transition(
            self.appt.id, AppointmentStatus.CANCELED)
        with self.assertRaises(InvalidTransitionError):
            Appointment.objects.transition(
                self.appt.id, AppointmentStatus.CONFIRMED)


# ── 4. Resilience ──────────────────────────────────────────────────────────

class RetryTest(TestCase):
    def test_retries_on_transient_error(self):
        attempts = {"n": 0}

        def fn():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("timeout")
            return "ok"
        result = RetryWithBackoff(max_attempts=3, base_delay=0)(fn)()
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["n"], 3)

    def test_raises_after_max_attempts(self):
        def fn(): raise ConnectionError("always")
        with self.assertRaises(ConnectionError):
            RetryWithBackoff(max_attempts=2, base_delay=0)(fn)()


class CircuitBreakerTest(TestCase):
    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=999)
        @cb
        def fail(): raise ConnectionError()
        with self.assertRaises(ConnectionError):
            fail()
        with self.assertRaises(ConnectionError):
            fail()
        with self.assertRaises(CircuitBreakerOpen):
            fail()

    def test_recovers_after_timeout(self):
        cb = CircuitBreaker(
            "test_recover", failure_threshold=1, recovery_timeout=0)

        @cb
        def fail(): raise ConnectionError()
        @cb
        def ok(): return "recovered"
        with self.assertRaises(ConnectionError):
            fail()
        time.sleep(0.01)
        self.assertEqual(ok(), "recovered")
