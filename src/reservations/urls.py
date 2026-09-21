from django.urls import path

from .views import (
    AvailabilityView,
    ReservationApproveView,
    ReservationCancelView,
    ReservationConfirmView,
    ReservationCreateView,
    ReservationRejectView,
)

urlpatterns = [
    path("reservations", ReservationCreateView.as_view(), name="reservation-create"),
    path(
        "reservations/<uuid:pk>/confirm",
        ReservationConfirmView.as_view(),
        name="reservation-confirm",
    ),
    path(
        "reservations/<uuid:pk>/cancel", ReservationCancelView.as_view(), name="reservation-cancel"
    ),
    path(
        "reservations/<uuid:pk>/approve",
        ReservationApproveView.as_view(),
        name="reservation-approve",
    ),
    path(
        "reservations/<uuid:pk>/reject", ReservationRejectView.as_view(), name="reservation-reject"
    ),
    path(
        "companions/<int:pk>/availability", AvailabilityView.as_view(), name="companion-availability"
    ),
]
