from django.core.management.base import BaseCommand

from billing.models import Invoice
from billing.tasks import send_invoice_email


class Command(BaseCommand):
    help = "Re-send invoice emails"

    def handle(self, *args, **options):
        for invoice in Invoice.objects.all():
            send_invoice_email.delay(invoice.id)
