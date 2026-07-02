from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("documents.urls")),
    path("api/", include("chat.urls")),
    path("api/", include("evaluations.urls")),
    path("api/", include("retrieval.urls")),
]
