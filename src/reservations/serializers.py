from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import Companion, Reservation


class ReservationCreateSerializer(serializers.ModelSerializer):
    companion_id = serializers.PrimaryKeyRelatedField(
        source="companion",
        queryset=Companion.objects.filter(is_active=True),
        error_messages={"does_not_exist": "Companion does not exist or is not active."},
    )
    customer_id = serializers.PrimaryKeyRelatedField(
        source="customer", queryset=get_user_model().objects.all()
    )

    class Meta:
        model = Reservation
        fields = ["id", "companion_id", "customer_id", "start_at", "end_at", "status"]
        read_only_fields = ["id", "status"]

    def validate(self, attrs):
        if attrs["start_at"] >= attrs["end_at"]:
            raise serializers.ValidationError({"end_at": "end_at must be after start_at."})
        if attrs["start_at"] <= timezone.now():
            raise serializers.ValidationError({"start_at": "start_at must be in the future."})
        if attrs["companion"].user_id == attrs["customer"].pk:
            raise serializers.ValidationError(
                {"customer_id": "A companion cannot book themselves."}
            )
        return attrs
