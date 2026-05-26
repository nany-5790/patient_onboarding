from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import PatientOnboardingSerializer
from .permissions import IsAdminOrClinicalStaff
from .models import AuditLog, OnboardingRequest, Patient


class PatientOnboardingView(APIView):
    permission_classes = [IsAdminOrClinicalStaff]

    def post(self, request):
        # Idempotencia — If existing onboarding request with same key, return existing patient info
        idempotency_key = request.data.get('idempotency_key')
        if idempotency_key:
            try:
                existing = OnboardingRequest.objects.select_related(
                    'patient__health_record'
                ).get(idempotency_key=idempotency_key)
                return Response(
                    {'id': existing.patient.id, 'status': 'already_onboarded'},
                    status=status.HTTP_200_OK,
                )
            except OnboardingRequest.DoesNotExist:
                pass

        serializer = PatientOnboardingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        patient = serializer.save()

        # Audit log — who created the patient and from where
        AuditLog.objects.create(
            actor=request.user,
            actor_ip=self._get_client_ip(request),
            action='patient.onboarded',
            resource_type='Patient',
            resource_id=patient.id,
            extra={'status': patient.status},
        )

        return Response(
            {'id': patient.id, 'status': patient.status},
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        # select_related for doctor (FK), prefetch related for health_record (OneToOne)
        patients = Patient.objects.select_related(
            'assigned_doctor'
        ).prefetch_related(
            'health_record'
        ).filter(status='active').order_by('-created_at')

        data = [
            {
                'id': p.id,
                'full_name': p.full_name,
                'status': p.status,
                'doctor': p.assigned_doctor.username if p.assigned_doctor else None,
            }
            for p in patients
        ]
        return Response(data)

    def _get_client_ip(self, request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
