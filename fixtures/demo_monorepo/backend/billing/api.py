from ninja import Router, Schema

from billing.models import Invoice

router = Router()


class LedgerLineSchema(Schema):
    amount: str
    kind: str


class InvoiceSchema(Schema):
    total: str
    lines: list[LedgerLineSchema]


@router.get("/invoices/{invoice_id}/ledger")
def invoice_ledger(request, invoice_id: int) -> InvoiceSchema:
    invoice = Invoice.objects.get(pk=invoice_id)
    return InvoiceSchema(total=str(invoice.total), lines=[])
