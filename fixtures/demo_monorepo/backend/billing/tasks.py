from celery import Task, chain, current_app, shared_task
from django.db import transaction

from billing.models import Invoice


@shared_task(bind=False)
def send_invoice_email(invoice_id):
    invoice = Invoice.objects.get(pk=invoice_id)
    return invoice.total


@shared_task
def apply_credit(invoice_id):
    Invoice.objects.filter(pk=invoice_id).update(status="credited")


class RecalcTotals(Task):
    name = "billing.recalc_totals"

    def run(self, invoice_id):
        invoice = Invoice.objects.get(pk=invoice_id)
        return invoice.total


def enqueue_email(invoice_id):
    transaction.on_commit(lambda: send_invoice_email.apply_async(args=[invoice_id]))


def settle_invoice(invoice_id):
    chain(apply_credit.s(invoice_id), send_invoice_email.si(invoice_id)).delay()
    current_app.send_task("billing.tasks.send_invoice_email", args=[invoice_id])
