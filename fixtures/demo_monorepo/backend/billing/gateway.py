from fastapi import FastAPI
from pydantic import BaseModel

from billing.models import Invoice

app = FastAPI()


class InvoiceOut(BaseModel):
    id: int
    total: float
    status: str


@app.get("/internal/invoices/{id}", response_model=InvoiceOut)
def get_invoice(id: int) -> InvoiceOut:
    row = Invoice.objects.get(pk=id)
    return InvoiceOut(id=row.id, total=float(row.total), status=row.status)
