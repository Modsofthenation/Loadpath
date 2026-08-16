from rest_framework import serializers

from billing.models import Invoice


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "customer_id", "total", "status"]


class LineSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    kind = serializers.CharField()


class InvoiceDetailSerializer(serializers.ModelSerializer):
    lines = LineSerializer(many=True)
    display_total = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ["id", "customer_id", "total", "status", "lines", "display_total"]

    def get_display_total(self, obj):
        return str(obj.total)

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "total": str(instance.total),
            "status": instance.status,
            "display_total": str(instance.total),
        }
