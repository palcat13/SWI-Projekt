from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Companion, Reservation, ReservationStatus, blocking_reservations
from .serializers import ActorSerializer, AvailabilityQuerySerializer, ReservationCreateSerializer

APPROVAL_WINDOW = timedelta(hours=24)
CONFIRMED_CANCEL_NOTICE = timedelta(hours=24)

CANCELLABLE_STATES = {
    ReservationStatus.DRAFT,
    ReservationStatus.PENDING_APPROVAL,
    ReservationStatus.CONFIRMED,
}


def conflict(code, detail):
    return Response({"error": code, "detail": detail}, status=status.HTTP_409_CONFLICT)


def forbidden(code, detail):
    return Response({"error": code, "detail": detail}, status=status.HTTP_403_FORBIDDEN)


def reservation_state(reservation):
    return {
        "id": str(reservation.id),
        "status": reservation.status,
        "approval_deadline": reservation.approval_deadline,
    }


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

        blocking = blocking_reservations(companion, start_at, end_at)
        return Response(
            {
                "companion_id": companion.pk,
                "start_at": start_at,
                "end_at": end_at,
                "available": companion.is_active and not blocking.exists(),
                "companion_active": companion.is_active,
                "blocking_reservations": [str(pk) for pk in blocking.values_list("id", flat=True)],
            }
        )


class ReservationConfirmView(APIView):
    def post(self, request, pk):
        actor = actor_or_error(request)
        with transaction.atomic():
            reservation = get_object_or_404(Reservation, pk=pk)
            if reservation.customer_id != actor.pk:
                return forbidden(
                    "FORBIDDEN_ACTOR", "Only the customer of the reservation can confirm it."
                )
            if reservation.status != ReservationStatus.DRAFT:
                return conflict("INVALID_STATE", f"Reservation is {reservation.status}, not DRAFT.")
            if not reservation.companion.is_active:
                return conflict("INACTIVE_RESOURCE", "The companion is not active.")

            now = timezone.now()
            if reservation.start_at <= now:
                return conflict("PAST_INTERVAL", "The reservation interval has already started.")
            if blocking_reservations(
                reservation.companion,
                reservation.start_at,
                reservation.end_at,
                exclude_id=reservation.id,
                now=now,
            ).exists():
                return conflict("OVERLAP", "The companion is not available for this interval.")

            if reservation.companion.requires_approval:
                reservation.status = ReservationStatus.PENDING_APPROVAL
                reservation.approval_requested_at = now
                reservation.approval_deadline = min(now + APPROVAL_WINDOW, reservation.start_at)
            else:
                reservation.status = ReservationStatus.CONFIRMED
            reservation.save()

        return Response(reservation_state(reservation))


class ReservationCancelView(APIView):
    def post(self, request, pk):
        actor = actor_or_error(request)
        with transaction.atomic():
            reservation = get_object_or_404(Reservation, pk=pk)
            allowed_actors = {reservation.customer_id, reservation.companion.user_id}
            if actor.pk not in allowed_actors:
                return forbidden(
                    "FORBIDDEN_ACTOR", "Only the customer or the booked companion can cancel."
                )
            if reservation.status == ReservationStatus.CANCELLED:
                return Response({**reservation_state(reservation), "idempotent": True})
            if reservation.status not in CANCELLABLE_STATES:
                return conflict(
                    "INVALID_STATE", f"A {reservation.status} reservation cannot be cancelled."
                )

            now = timezone.now()
            if reservation.status == ReservationStatus.CONFIRMED:
                if now > reservation.start_at - CONFIRMED_CANCEL_NOTICE:
                    return conflict(
                        "TOO_LATE",
                        "A confirmed reservation can only be cancelled 24 h before its start.",
                    )
            elif now >= reservation.start_at:
                return conflict("TOO_LATE", "The reservation interval has already started.")

            reservation.status = ReservationStatus.CANCELLED
            reservation.save()

        return Response(reservation_state(reservation))


class ApprovalDecisionView(APIView):
    """Shared checks for Approve and Reject: only the booked companion decides, before the deadline."""

    target_status = None

    def post(self, request, pk):
        actor = actor_or_error(request)
        with transaction.atomic():
            reservation = get_object_or_404(Reservation, pk=pk)
            if reservation.companion.user_id != actor.pk:
                return forbidden(
                    "FORBIDDEN_ACTOR", "Only the booked companion can decide about this request."
                )
            if reservation.status != ReservationStatus.PENDING_APPROVAL:
                return conflict(
                    "INVALID_STATE",
                    f"Reservation is {reservation.status}, not PENDING_APPROVAL.",
                )

            now = timezone.now()
            if reservation.approval_deadline <= now:
                reservation.status = ReservationStatus.EXPIRED
                reservation.save()
                return conflict("EXPIRED", "The approval window has already closed.")

            if self.target_status == ReservationStatus.CONFIRMED and blocking_reservations(
                reservation.companion,
                reservation.start_at,
                reservation.end_at,
                exclude_id=reservation.id,
                now=now,
            ).exists():
                return conflict("OVERLAP", "The interval is already blocked by another reservation.")

            reservation.status = self.target_status
            reservation.decided_by = actor
            reservation.save()

        return Response(reservation_state(reservation))


class ReservationApproveView(ApprovalDecisionView):
    target_status = ReservationStatus.CONFIRMED


class ReservationRejectView(ApprovalDecisionView):
    target_status = ReservationStatus.REJECTED
