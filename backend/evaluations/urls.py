from django.urls import path

from .views import EvaluationRunListView, RunEvaluationView

urlpatterns = [
    path("evaluations/", EvaluationRunListView.as_view(), name="evaluation-list"),
    path("evaluations/run/", RunEvaluationView.as_view(), name="evaluation-run"),
]
