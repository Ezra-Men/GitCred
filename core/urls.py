from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.index_view, name="index"),
    path("audit/", views.audit_user_view, name="audit"),
    path("passport/<str:username>/", views.passport_view, name="passport"),
    path("badge/<str:username>.svg", views.badge_view, name="badge"),
]