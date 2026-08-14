from django.urls import path

from accounts.views import MeView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("login/", MeView.as_view(), name="login"),
]
