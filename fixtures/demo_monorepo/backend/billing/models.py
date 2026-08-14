from django.db import models


class Invoice(models.Model):
    customer_id = models.IntegerField()
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=32, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "billing"
