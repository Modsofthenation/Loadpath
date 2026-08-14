import dramatiq

from billing.models import Invoice


@dramatiq.actor
def rebuild_ledger(invoice_id):
    invoice = Invoice.objects.get(pk=invoice_id)
    return str(invoice.total)


class NotifyCustomer(dramatiq.GenericActor):
    def perform(self, invoice_id):
        invoice = Invoice.objects.get(pk=invoice_id)
        return invoice.status
