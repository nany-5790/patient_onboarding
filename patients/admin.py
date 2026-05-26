from django.contrib import admin
from .models import Patient, HealthRecord, AuditLog, OnboardingRequest


class HealthRecordInline(admin.StackedInline):
    model = HealthRecord
    extra = 0


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email',
                    'status', 'created_at', 'assigned_doctor']
    list_filter = ['status']
    search_fields = ['full_name', 'email']
    inlines = [HealthRecordInline]
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'actor',
                    'resource_type', 'resource_id', 'timestamp']
    list_filter = ['action', 'resource_type']
    readonly_fields = [f.name for f in AuditLog._meta.fields]  # all readonly

    def has_add_permission(self, request):
        return False  # nobody can create logs manually

    def has_delete_permission(self, request, obj=None):
        return False  # nobody can delete them
