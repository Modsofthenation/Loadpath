from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    operations = [
        migrations.CreateModel(
            name="Invoice",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("total", models.DecimalField(max_digits=10, decimal_places=2)),
            ],
        ),
    ]
