from django.contrib import admin

from .models import Companion, Reservation


@admin.register(Companion)
class CompanionAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "is_active", "requires_approval", "created_at")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "companion",
        "customer",
        "start_at",
        "end_at",
        "status",
        "approval_deadline",
    )
    list_filter = ("status",)
