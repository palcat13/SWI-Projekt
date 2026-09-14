import uuid

from django.conf import settings
from django.db import models


class Companion(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="companion_profile"
    )
    display_name = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name


class ReservationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"


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
    status =models.CharField(
        max_length=20, choices=ReservationStatus.choices, default=ReservationStatus.DRAFT
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
