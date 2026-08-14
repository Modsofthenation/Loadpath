from rest_framework import serializers

from accounts.models import UserProfile


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["id", "email", "display_name"]
