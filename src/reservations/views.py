from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import availability, lifecycle
from .models import Companion, Reservation
from .serializers import ActorSerializer, AvailabilityQuerySerializer, ReservationCreateSerializer

REFUSAL_STATUS = {
    lifecycle.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    lifecycle.CONFLICT: status.HTTP_409_CONFLICT,
}


def reservation_state(reservation):
    return {
        "id": str(reservation.id),
        "status": reservation.status,
        "approval_deadline": reservation.approval_deadline,
    }


def refusal_response(refused: lifecycle.TransitionRefused) -> Response:
    return Response(
        {"error": refused.code, "detail": refused.detail}, status=REFUSAL_STATUS[refused.kind]
    )


def actor_or_error(request):
    serializer = ActorSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["actor_user_id"]


class ReservationCreateView(APIView):
    def post(self, request):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = serializer.save()
        return Response(
            {"id": str(reservation.id), "status": reservation.status},
            status=status.HTTP_201_CREATED,
        )


class AvailabilityView(APIView):
    def get(self, request, pk):
        companion = get_object_or_404(Companion, pk=pk)
        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start_at = query.validated_data["start_at"]
        end_at = query.validated_data["end_at"]

        now = timezone.now()
        blocking = availability.blocking_reservations(companion, start_at, end_at, now=now)
        return Response(
            {
                "companion_id": companion.pk,
                "start_at": start_at,
                "end_at": end_at,
                "available": availability.is_available(companion, start_at, end_at, now=now),
                "companion_active": companion.is_active,
                "blocking_reservations": [str(pk) for pk in blocking.values_list("id", flat=True)],
            }
        )


class TransitionView(APIView):
    """Thin adapter: resolves the actor, delegates the transition, maps the outcome to HTTP."""

    transition = None

    def post(self, request, pk):
        actor = actor_or_error(request)
        reservation = get_object_or_404(Reservation, pk=pk)
        try:
            outcome = self.transition(reservation, actor)
        except lifecycle.TransitionRefused as refused:
            return refusal_response(refused)

        body = reservation_state(outcome.reservation)
        if outcome.idempotent:
            body["idempotent"] = True
        return Response(body)


class ReservationConfirmView(TransitionView):
    transition = staticmethod(lifecycle.confirm)


class ReservationCancelView(TransitionView):
    transition = staticmethod(lifecycle.cancel)


class ReservationApproveView(TransitionView):
    transition = staticmethod(lifecycle.approve)


class ReservationRejectView(TransitionView):
    transition = staticmethod(lifecycle.reject)
