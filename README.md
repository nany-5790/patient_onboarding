# patient_onboarding

A Django REST Framework API for patient onboarding, built with production-grade patterns for medical data systems.

## Features

- **Idempotent onboarding endpoint** — safe to retry without duplicating patients
- **Role-based access control (RBAC)** — only authorized clinical staff can onboard patients
- **Immutable audit logs** — every action on patient data is tracked and cannot be edited or deleted
- **PHI separation** — patient identity data and clinical records stored in separate models
- **Atomic transactions** — patient, health record, and onboarding request created together or not at all
- **Optimized queries** — `select_related` and `prefetch_related` to avoid N+1 problems

## Stack

- Python 3.x
- Django 4.2+
- Django REST Framework 3.14+
- SQLite (demo) / PostgreSQL (production-ready)

## Setup

```bash
git clone https://github.com/your_username/patient_onboarding.git
cd patient_onboarding

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the root directory:

```
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

Run migrations and create a superuser:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Create the `clinical_staff` group and assign it to your user:

```bash
python manage.py shell
```

```python
from django.contrib.auth.models import User, Group
group = Group.objects.create(name='clinical_staff')
user = User.objects.get(username='your_username')
user.groups.add(group)
exit()
```

Start the server:

```bash
python manage.py runserver
```

## API

### POST `/api/v1/patients/onboard/`

Onboards a new patient. Requires authentication and `clinical_staff` role or admin.

**Request:**

```json
{
  "full_name": "Jane Doe",
  "date_of_birth": "1990-05-15",
  "email": "jane@example.com",
  "phone": "555-1234",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "health_record": {
    "insurance_provider": "BlueCross",
    "insurance_id": "BC-12345",
    "allergies": "penicillin",
    "notes": ""
  }
}
```

**First request — patient created:**
```json
{"id": "5e010a2a-46f3-427c-917a-96b49418e799", "status": "pending"}
```

**Same `idempotency_key` — safe retry:**
```json
{"id": "5e010a2a-46f3-427c-917a-96b49418e799", "status": "already_onboarded"}
```

### GET `/api/v1/patients/onboard/`

Returns all active patients with their assigned doctor. Uses `select_related` and `prefetch_related` to avoid N+1 queries.

## Admin

Access the Django admin at `http://127.0.0.1:8000/admin/`:

- **Patients** — view patients with inline health records
- **Audit Logs** — read-only, no add or delete permissions
- **Onboarding Requests** — idempotency key registry

## Tests

```bash
python manage.py test patients
```

Covers:
- Patient creation happy path
- Idempotency — same key returns `already_onboarded`
- Unauthorized user receives `403 Forbidden`
- Audit log created on every onboarding

## Design Decisions

**Idempotency** — every onboarding request requires an `idempotency_key`. If the same key is sent twice, the API returns the original result without creating a duplicate patient. Safe for retries and network failures.

**PHI separation** — `Patient` stores identity data, `HealthRecord` stores clinical data in a separate table. Smaller attack surface — a query on one table doesn't expose the other.

**Immutable audit logs** — `AuditLog` records cannot be edited or deleted, enforced at the model level and in the Django admin. Every access to patient data leaves a trace.

**Atomic transactions** — `Patient`, `HealthRecord`, and `OnboardingRequest` are created inside a single `transaction.atomic()` block. Either all three are created or none of them are.

**RBAC** — access is restricted to users in the `clinical_staff` group or Django admins. Queryset-level filtering ensures users only see data they are authorized to access.
