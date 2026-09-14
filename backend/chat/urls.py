from django.urls import path

from .views import (
    ActiveCollectionAnalysesView,
    ChatHistoryView,
    ChatQueryView,
    CollectionAnalysisControlView,
    CollectionAnalysisReferencesView,
    CollectionAnalysisView,
)

urlpatterns = [
    path(
        "chat/analysis/<uuid:analysis_id>/references/",
        CollectionAnalysisReferencesView.as_view(),
        name="chat-analysis-references",
    ),
    path(
        "chat/analyses/active/",
        ActiveCollectionAnalysesView.as_view(),
        name="chat-analyses-active",
    ),
    path(
        "chat/analysis/<uuid:analysis_id>/control/",
        CollectionAnalysisControlView.as_view(),
        name="chat-analysis-control",
    ),
    path(
        "chat/analysis/<uuid:analysis_id>/",
        CollectionAnalysisView.as_view(),
        name="chat-analysis",
    ),
    path("chat/query/", ChatQueryView.as_view(), name="chat-query"),
    path("chat/history/", ChatHistoryView.as_view(), name="chat-history"),
]
