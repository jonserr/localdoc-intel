from django.contrib import admin

from .models import Collection, Document, DocumentChunk


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "document_count", "created_at")
    search_fields = ("name",)

    @admin.display(description="Documents")
    def document_count(self, obj: Collection) -> int:
        return obj.documents.count()


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "collection",
        "file_type",
        "status",
        "chunk_count",
        "created_at",
    )
    list_filter = ("status", "file_type", "collection")
    search_fields = ("title", "original_filename", "sha256")


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "start_line", "end_line", "token_count")
    list_filter = ("document__collection",)
    search_fields = ("document__title", "text")
