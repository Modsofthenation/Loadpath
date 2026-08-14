from ninja import Router

from billing.models import Invoice

router = Router()


@router.get("/invoices/{invoice_id}/ledger")
def invoice_ledger(request, invoice_id: int):
    invoice = Invoice.objects.get(pk=invoice_id)
    return {"total": str(invoice.total)}
