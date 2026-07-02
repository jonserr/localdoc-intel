from rest_framework import serializers

from .models import Collection, Document, DocumentChunk


class CollectionSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = [
            "id",
            "name",
            "description",
            "document_count",
            "created_at",
            "updated_at",
        ]

    def get_document_count(self, obj: Collection) -> int:
        return getattr(obj, "document_total", obj.documents.count())


class DocumentSerializer(serializers.ModelSerializer):
    collection = CollectionSerializer(read_only=True)
    collection_id = serializers.PrimaryKeyRelatedField(
        source="collection",
        queryset=Collection.objects.all(),
        write_only=True,
    )

    class Meta:
        model = Document
        fields = [
            "id",
            "collection",
            "collection_id",
            "title",
            "original_filename",
            "file_type",
            "sha256",
            "source_path",
            "metadata",
            "status",
            "error_message",
            "chunk_count",
            "byte_size",
            "created_at",
            "updated_at",
            "last_indexed_at",
        ]
        read_only_fields = [
            "chunk_count",
            "created_at",
            "updated_at",
            "last_indexed_at",
            "source_path",
            "metadata",
        ]


class DocumentChunkSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source="document.title", read_only=True)
    document_collection = serializers.CharField(
        source="document.collection.name",
        read_only=True,
    )
    text_preview = serializers.SerializerMethodField()

    class Meta:
        model = DocumentChunk
        fields = [
            "id",
            "document",
            "document_title",
            "document_collection",
            "chunk_index",
            "text",
            "text_preview",
            "page",
            "start_line",
            "end_line",
            "byte_start",
            "byte_end",
            "token_count",
            "embedding_id",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_text_preview(self, obj: DocumentChunk) -> str:
        text = " ".join(obj.text.split())
        return text[:240]
