import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Companion(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="companion_profile"
    )
    display_name = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name


class ReservationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"


class Activity(models.TextChoices):
    DINNER = "DINNER", "Dinner"
    EVENT = "EVENT", "Event"
    WALK = "WALK", "Walk"
    OTHER = "OTHER", "Other"


class Reservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    companion = models.ForeignKey(Companion, on_delete=models.PROTECT, related_name="reservations")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservations"
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    activity = models.CharField(max_length=20, choices=Activity.choices, default=Activity.OTHER)
    status = models.CharField(
        max_length=20, choices=ReservationStatus.choices, default=ReservationStatus.DRAFT
    )
    approval_requested_at = models.DateTimeField(null=True, blank=True)
    approval_deadline = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservation_decisions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_at__lt=models.F("end_at")),
                name="reservation_start_before_end",
            ),
        ]

    def __str__(self):
        return f"{self.id} ({self.status})"


def blocking_reservations(companion, start_at, end_at, exclude_id=None, now=None):
    """Reservations of `companion` that block the half-open interval [start_at, end_at) (BR-01, BR-02)."""
    now = now or timezone.now()
    queryset = Reservation.objects.filter(
        companion=companion, start_at__lt=end_at, end_at__gt=start_at
    ).filter(
        Q(status=ReservationStatus.CONFIRMED)
        | Q(status=ReservationStatus.PENDING_APPROVAL, approval_deadline__gt=now)
    )
    if exclude_id is not None:
        queryset = queryset.exclude(id=exclude_id)
    return queryset
