from django.db import models


class UserProfile(models.Model):
    email = models.EmailField()
    display_name = models.CharField(max_length=120)

    class Meta:
        app_label = "accounts"
