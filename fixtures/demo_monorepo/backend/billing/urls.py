from django.urls import include, path
from rest_framework.routers import DefaultRouter

from billing.views import InvoiceBoardView, InvoiceViewSet, graphql_http, invoice_totals

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("", include(router.urls)),
    path("invoices/totals/", invoice_totals, name="invoice-totals"),
    path("invoices/board/", InvoiceBoardView.as_view(), name="invoice-board"),
    path("graphql/", graphql_http, name="graphql"),
    path(
        "invoices/<int:id>/",
        InvoiceViewSet.as_view({"get": "retrieve", "put": "update"}),
        name="invoice-detail",
    ),
]
