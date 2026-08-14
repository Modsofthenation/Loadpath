from celery import shared_task

from billing.models import Invoice


@shared_task
def send_invoice_email(invoice_id):
    invoice = Invoice.objects.get(pk=invoice_id)
    return invoice.total
