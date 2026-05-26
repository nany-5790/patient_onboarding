# patients/tests.py
from django.test import TestCase
from django.contrib.auth.models import User, Group
from rest_framework.test import APIClient
import uuid


class PatientOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.group = Group.objects.create(name='clinical_staff')
        self.user = User.objects.create_user('nurse1', password='pass')
        self.user.groups.add(self.group)
        self.client.force_authenticate(user=self.user)
        self.payload = {
            'full_name': 'Jane Doe',
            'date_of_birth': '1990-05-15',
            'email': 'jane@example.com',
            'phone': '555-1234',
            'idempotency_key': str(uuid.uuid4()),
            'health_record': {
                'insurance_provider': 'BlueCross',
                'insurance_id': 'BC-12345',
                'allergies': 'penicillin',
                'notes': '',
            }
        }

    def test_onboarding_creates_patient(self):
        response = self.client.post(
            '/api/v1/patients/onboard/', self.payload, format='json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('id', response.data)

    def test_idempotency_returns_same_result(self):
        # Primera request
        r1 = self.client.post(
            '/api/v1/patients/onboard/', self.payload, format='json'
        )
        self.assertEqual(r1.status_code, 201)

        # Segunda request con mismo idempotency_key
        r2 = self.client.post(
            '/api/v1/patients/onboard/', self.payload, format='json'
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data['status'], 'already_onboarded')

    def test_unauthorized_user_cannot_onboard(self):
        unauth_client = APIClient()
        unauth_user = User.objects.create_user('hacker', password='pass')
        unauth_client.force_authenticate(user=unauth_user)

        response = unauth_client.post(
            '/api/v1/patients/onboard/', self.payload, format='json'
        )
        self.assertEqual(response.status_code, 403)

    def test_audit_log_created_on_onboarding(self):
        from patients.models import AuditLog
        self.client.post(
            '/api/v1/patients/onboard/', self.payload, format='json'
        )
        log = AuditLog.objects.filter(action='patient.onboarded').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.user)
