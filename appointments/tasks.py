import uuid
from celery import shared_task
from core.observability import logger, metrics, trace, track_latency
from core.resilience import (
    RetryWithBackoff, notification_circuit,
    with_fallback, CircuitBreakerOpen
)


# ── Fallback: cuando el servicio de notificaciones está caído ──────────────
# -- Fallback: When notification's service are down---------------

def _queue_notification_locally(patient_id, message, **kwargs):
    """Plan B: guarda en DB/Redis para enviar después."""
    logger.warning("notification.queued_locally", patient_id=patient_id)
    metrics.increment("notifications.fallback.queued")
    # En producción: PendingNotification.objects.create(...)
    return {"queued_locally": True}


# Real call to external notification service (Twilio/SendGrid/FCM)
# ── La llamada real al servicio externo (Twilio/SendGrid/FCM) ──────────────
# Decorators are applied from the outside in:
# track latency → with fallback → circuit_breaker → retry → actual call
# Los decoradores se aplican de afuera hacia adentro:
# track_latency → with_fallback → circuit_breaker → retry → llamada real

@track_latency("notifications.send")
@with_fallback(_queue_notification_locally, catch=(CircuitBreakerOpen, ConnectionError, TimeoutError))
@notification_circuit
@RetryWithBackoff(max_attempts=3, base_delay=1.0, exceptions=(ConnectionError, TimeoutError))
def _notify_patient(patient_id, message, trace_id=""):
    logger.info("notification.sending",
                patient_id=patient_id, trace_id=trace_id)
    # Here goes the actual requests.post() call to the notification service.
    # Aquí va el requests.post() real al servicio de notificaciones
    logger.info("notification.sent", patient_id=patient_id, trace_id=trace_id)


# ── Celery task principal ──────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name="appointments.send_confirmation")
def send_confirmation(self, appointment_id, trace_id=None):
    trace_id = trace_id or str(uuid.uuid4())

    with trace("appointments.send_confirmation", trace_id=trace_id):
        try:
            from appointments.models import Appointment
            appt = Appointment.objects.select_related("patient", "provider").get(
                pk=appointment_id
            )
            message = (
                f"Tu cita con {appt.provider.name} está confirmada "
                f"para el {appt.start_time:%d/%m/%Y a las %H:%M}."
            )
            _notify_patient(patient_id=appt.patient.id,
                            message=message, trace_id=trace_id)
            metrics.increment("appointments.confirmation_sent")

        except Exception as exc:
            logger.error("task.failed", task="send_confirmation",
                         appointment_id=appointment_id, error=str(exc), trace_id=trace_id)
            raise self.retry(exc=exc)
