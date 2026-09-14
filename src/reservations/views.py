from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ReservationCreateSerializer


class ReservationCreateView(APIView):
    def post(self, request):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = serializer.save()
        return Response(
            {"id": str(reservation.id), "status": reservation.status},
            status=status.HTTP_201_CREATED,
        )
