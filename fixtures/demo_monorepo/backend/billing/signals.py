from django.db.models.signals import post_save
from django.dispatch import receiver

from billing.models import Invoice


@receiver(post_save, sender=Invoice)
def update_ledger(sender, instance, **kwargs):
    # Formats Invoice.total into a ledger row — no test covers this.
    _ = f"{instance.total:.2f}"
