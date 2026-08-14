from billing.models import Invoice


def recalculate_total(invoice: Invoice) -> Invoice:
    invoice.total = invoice.total
    invoice.save(update_fields=["total"])
    return invoice


def overdue_account_emails():
    """Classic N+1: related FK accessed per row with no select_related."""
    names = []
    for invoice in Invoice.objects.filter(status="open"):
        names.append(invoice.account.email)
    return names
