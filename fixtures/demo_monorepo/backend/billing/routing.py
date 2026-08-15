from django.urls import path

from billing.consumers import InvoiceConsumer

websocket_urlpatterns = [
    path("ws/invoices/", InvoiceConsumer.as_asgi()),
]
