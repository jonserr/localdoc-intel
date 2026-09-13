from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CollectionViewSet,
    DocumentChunkViewSet,
    DocumentViewSet,
    IngestFolderView,
    UploadDocumentView,
    health,
    local_settings,
    stats,
    status_view,
)

router = DefaultRouter()
router.register("collections", CollectionViewSet, basename="collection")
router.register("documents", DocumentViewSet, basename="document")
router.register("chunks", DocumentChunkViewSet, basename="chunk")

urlpatterns = [
    path("health/", health, name="health"),
    path("status/", status_view, name="status"),
    path("stats/", stats, name="stats"),
    path("settings/", local_settings, name="settings"),
    path("documents/upload/", UploadDocumentView.as_view(), name="document-upload"),
    path(
        "documents/ingest-folder/",
        IngestFolderView.as_view(),
        name="document-ingest-folder",
    ),
    path("", include(router.urls)),
]
