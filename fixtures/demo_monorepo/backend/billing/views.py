from django.core.cache import cache
from django.db import transaction
from django.views.generic import TemplateView
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from waffle import flag_is_active

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
        cache.delete("invoice:list")
        send_invoice_email.delay(invoice.id)
        rebuild_ledger.send(invoice.id)
        rebuild_ledger.send_with_options(args=(invoice.id,))
        if flag_is_active(self.request, "async_ledger"):
            transaction.on_commit(lambda: rebuild_ledger.send(invoice.id))
        return invoice


class InvoiceBoardView(TemplateView):
    template_name = "billing/invoice_board.html"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_totals(request):
    if flag_is_active(request, "new_totals"):
        cached = cache.get("invoice:totals")
        if cached is not None:
            return Response({"count": cached})
        count = Invoice.objects.count()
        cache.set("invoice:totals", count)
        return Response({"count": count})
    return Response({"count": Invoice.objects.count()})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def graphql_http(request):
    return Response({"data": {}})
