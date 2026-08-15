from channels.generic.websocket import AsyncJsonWebsocketConsumer

from billing.models import Invoice


class InvoiceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def receive_json(self, content, **kwargs):
        invoice_id = content.get("id")
        invoice = Invoice.objects.get(pk=invoice_id)
        await self.send_json({"id": invoice.id, "total": str(invoice.total)})
