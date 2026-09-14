from django.urls import path

from .views import ReservationCreateView

urlpatterns = [
    path("reservations", ReservationCreateView.as_view(), name="reservation-create"),
]
