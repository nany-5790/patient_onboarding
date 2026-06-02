class DoubleBookingError(Exception):
    """El slot solicitado se solapa con uno existente."""


class InvalidTransitionError(Exception):
    """La transición de estado no está permitida."""
