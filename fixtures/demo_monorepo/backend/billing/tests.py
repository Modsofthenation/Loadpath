from rest_framework.test import APITestCase

from billing.models import Invoice
from billing.serializers import InvoiceSerializer
from billing.views import InvoiceViewSet


class InvoiceSerializerTests(APITestCase):
    def test_serializer_includes_total(self):
        data = InvoiceSerializer(Invoice(customer_id=1, total="10.00", status="draft")).data
        assert "total" in data


class InvoiceViewTests(APITestCase):
    def test_viewset_uses_invoice_serializer(self):
        assert InvoiceViewSet.serializer_class is InvoiceSerializer
