from billing.models import Invoice


def recalculate_total(invoice: Invoice) -> Invoice:
    invoice.total = invoice.total
    invoice.save(update_fields=["total"])
    return invoice
