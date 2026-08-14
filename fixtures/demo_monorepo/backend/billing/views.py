from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from billing.models import Invoice
from billing.serializers import InvoiceSerializer
from billing.tasks import send_invoice_email


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    queryset = Invoice.objects.all()

    def perform_create(self, serializer):
        invoice = serializer.save()
        send_invoice_email.delay(invoice.id)
        return invoice
