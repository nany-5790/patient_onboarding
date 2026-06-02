import time
import random
import threading
import functools
from enum import Enum
from core.observability import logger, metrics


# ── Retry with exponential backoff ─────────────────────────────────────────

class RetryWithBackoff:
    def __init__(self, max_attempts=3, base_delay=1.0,
                 max_delay=30.0, exceptions=(Exception,)):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exceptions = exceptions

    def __call__(self, fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except self.exceptions as exc:
                    if attempt >= self.max_attempts:
                        logger.error("retry.exhausted",
                                     fn=fn.__name__, attempts=attempt)
                        raise
                    # Exponential: base * 2^(attempt-1) + jitter
                    delay = min(
                        self.base_delay * (2 ** (attempt - 1)) +
                        random.uniform(0, 1),
                        self.max_delay,
                    )
                    logger.warning("retry.attempt", fn=fn.__name__,
                                   attempt=attempt, next_in=round(delay, 2))
                    time.sleep(delay)
        return wrapper


# ── Circuit Breaker ────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    pass


class CircuitBreaker:
    def __init__(self, name, failure_threshold=5,
                 window_seconds=60, recovery_timeout=30):
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failures = []   # timestamps de fallos recientes
        self._opened_at = None
        self._lock = threading.Lock()

    def _record_failure(self):
        now = time.time()
        # Slide the window — discard old failures.
        # Desliza la ventana — descarta fallos viejos
        self._failures = [
            t for t in self._failures if now - t < self.window_seconds]
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = now
            logger.warning("circuit_breaker.opened", name=self.name)
            metrics.increment("circuit_breaker.opened",
                              tags=[f"name:{self.name}"])

    def __call__(self, fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with self._lock:
                # Check if recovery timeout has passed
                # Chequea si pasó el timeout de recovery
                if (self._state == CircuitState.OPEN
                        and self._opened_at
                        and time.time() - self._opened_at >= self.recovery_timeout):
                    self._state = CircuitState.HALF_OPEN
                    logger.info("circuit_breaker.half_open", name=self.name)

                if self._state == CircuitState.OPEN:
                    metrics.increment("circuit_breaker.blocked", tags=[
                                      f"name:{self.name}"])
                    raise CircuitBreakerOpen(f"Circuit '{self.name}' is OPEN.")

            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    if self._state == CircuitState.HALF_OPEN:
                        self._state = CircuitState.CLOSED
                        self._failures.clear()
                        logger.info("circuit_breaker.closed", name=self.name)
                return result
            except CircuitBreakerOpen:
                raise
            except Exception as exc:
                with self._lock:
                    self._record_failure()
                raise
        return wrapper


# ── Fallback ───────────────────────────────────────────────────────────────

def with_fallback(fallback_fn, catch=(Exception,)):
    """
    Si la función falla con alguna de las excepciones en `catch`,
    llama a `fallback_fn` con los mismos argumentos.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except catch as exc:
                logger.warning("fallback.triggered",
                               fn=fn.__name__,
                               fallback=fallback_fn.__name__,
                               reason=str(exc))
                metrics.increment("fallback.triggered",
                                  tags=[f"fn:{fn.__name__}"])
                return fallback_fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Circuit breakers pre-configurados per service ────────────────────────

notification_circuit = CircuitBreaker(
    name="notification_service", failure_threshold=3, recovery_timeout=30
)
ehr_circuit = CircuitBreaker(
    name="ehr_integration", failure_threshold=5, recovery_timeout=60
)
