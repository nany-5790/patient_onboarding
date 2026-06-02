import time
import uuid
import logging
import functools
from contextlib import contextmanager


# ── Structured logger ──────────────────────────────────────────────────────
# In production, you would configure this logger to output JSON or
# use a structured logging library.
# For now we'll just log dicts for simplicity.
# En producción configurás el handler para que emita JSON real.
# Por ahora los dicts son suficientes para mostrar el patrón.

class StructuredLogger:
    def __init__(self, service: str):
        self._log = logging.getLogger(service)
        self.service = service

    def _emit(self, level: str, event, **ctx):
        msg = {
            "service": self.service,
            "event": event,
            **ctx
        }
        getattr(self._log, level)(msg)

    def info(self, event, **ctx):
        self._emit("info", event, **ctx)

    def warning(self, event, **ctx):
        self._emit("warning", event, **ctx)

    def error(self, event, **ctx):
        self._emit("error", event, **ctx)


logger = StructuredLogger("patient_onboarding")

# ── Metrics stub ───────────────────────────────────────────────────────────
# To Connect to real Datadog, replace the body of each method with:
#   from datadog import statsd
#   statsd.increment(metric, tags=tags)
# Para conectar Datadog real, reemplazá el body de cada método:
#   from datadog import statsd
#   statsd.increment(metric, tags=tags)


class MetricsClient:
    def increment(self, metric, tags=None):
        logger._emit("debug", "metric.increment",
                     metric=metric, tags=tags or [])

    def histogram(self, metric, value, tags=None):
        logger._emit("debug", "metric.histogram", metric=metric,
                     value=round(value, 2), tags=tags or [])


metrics = MetricsClient()

# ── Distributed trace context manager ─────────────────────────────────────


class Span:
    def __init__(self, operation, trace_id=None):
        self.operation = operation
        self.trace_id = trace_id or str(uuid.uuid4())
        self._start = time.perf_counter()

    def finish(self, error=False):
        duration_ms = (time.perf_counter() - self._start) * 1000
        logger.info(
            "trace.span.finish",
            operation=self.operation,
            trace_id=self.trace_id,
            duration_ms=round(duration_ms, 2),
            status="error" if error else "ok",
        )
        metrics.histogram(f"{self.operation}.duration_ms", duration_ms)


@contextmanager
def trace(operation, trace_id=None):
    """
    Uso:
        with trace("appointments.book", trace_id=req_trace_id) as span:
            ...
    """
    span = Span(operation, trace_id)
    logger.info("trace.span.start", operation=operation,
                trace_id=span.trace_id)
    try:
        yield span
        span.finish(error=False)
    except Exception:
        span.finish(error=True)
        raise

# ── Decorator de latencia ──────────────────────────────────────────────────


def track_latency(operation):
    """
    Uso:
        @track_latency("notifications.send")
        def send_sms(patient_id): ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            error = False
            try:
                return fn(*args, **kwargs)
            except Exception:
                error = True
                metrics.increment(f"{operation}.error")
                raise
            finally:
                ms = (time.perf_counter() - start) * 1000
                metrics.histogram(f"{operation}.latency_ms", ms,
                                  tags=[f"error:{error}"])
        return wrapper
    return decorator
