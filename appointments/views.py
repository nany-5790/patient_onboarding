from core.observability import logger, metrics, trace
from appointments.exceptions import DoubleBookingError, InvalidTransitionError
from appointments.serializers import (
    AppointmentCreateSerializer, AppointmentSerializer, TransitionSerializer
)
from appointments.models import Appointment
import uuid
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response


class AppointmentViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["post"], url_path="book")
    def book(self, request):
        # trace_id travel with the whole workflow
        # trace_id viaja con todo el workflow
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

        serializer = AppointmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        with trace("appointments.book_view", trace_id=trace_id):
            try:
                appt = Appointment.objects.book(
                    patient_id=data["patient_id"],
                    provider_id=data["provider_id"],
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    appointment_type=data["appointment_type"],
                    idempotency_key=str(data["idempotency_key"]),
                )

                # Trigger async workflow to send confirmation email
                # from appointments.tasks import send_confirmation
                # send_confirmation.delay(appt.id, trace_id=trace_id)

                logger.info("appointment.booked",
                            appointment_id=appt.id, trace_id=trace_id)
                metrics.increment("appointments.booked")

                return Response(
                    AppointmentSerializer(appt).data,
                    status=status.HTTP_201_CREATED,
                    headers={"X-Trace-ID": trace_id},
                )

            except DoubleBookingError as e:
                logger.warning(
                    "appointment.double_booking_blocked", trace_id=trace_id)
                metrics.increment("appointments.double_booking_blocked")
                return Response(
                    {"error": "double_booking", "detail": str(e)},
                    status=status.HTTP_409_CONFLICT,
                )

    @action(detail=True, methods=["patch"], url_path="transition")
    def transition(self, request, pk=None):
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        serializer = TransitionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            appt = Appointment.objects.transition(
                appointment_id=int(pk),
                new_status=serializer.validated_data["status"],
            )
            logger.info("appointment.transitioned",
                        appointment_id=pk,
                        new_status=appt.status,
                        trace_id=trace_id)
            return Response(AppointmentSerializer(appt).data)

        except InvalidTransitionError as e:
            return Response(
                {"error": "invalid_transition", "detail": str(e)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
