from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from billing.actors import rebuild_ledger
from billing.models import Invoice
from billing.serializers import InvoiceSerializer
from billing.tasks import send_invoice_email


class InvoiceFilter:
    """Stand-in for django-filter FilterSet (parsed as filterset_class)."""


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = InvoiceFilter
    queryset = Invoice.objects.all()

    def get_queryset(self):
        return Invoice.objects.select_related()

    def perform_create(self, serializer):
        invoice = serializer.save()
        send_invoice_email.delay(invoice.id)
        rebuild_ledger.send(invoice.id)
        rebuild_ledger.send_with_options(args=(invoice.id,))
        return invoice


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_totals(request):
    return Response({"count": Invoice.objects.count()})
