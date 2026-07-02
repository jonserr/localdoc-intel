from documents.models import Collection
from rest_framework import serializers

from .models import ChatQuery


class ChatQueryRequestSerializer(serializers.Serializer):
    question = serializers.CharField(trim_whitespace=True)
    collection = serializers.CharField(required=False, allow_blank=True)
    retrieval_mode = serializers.ChoiceField(
        choices=["vector", "hybrid", "metadata-filtered"],
        default="hybrid",
    )
    top_k = serializers.IntegerField(min_value=1, max_value=20, default=5)
    rerank = serializers.BooleanField(default=False)

    def validate_question(self, value: str) -> str:
        if not value:
            raise serializers.ValidationError("Question cannot be blank.")
        return value

    def validate_collection(self, value: str) -> str:
        if value and not Collection.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError(f"Unknown collection '{value}'.")
        return value


class ChatQuerySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatQuery
        fields = [
            "id",
            "question",
            "answer",
            "retrieval_mode",
            "retrieval_top_k",
            "collection",
            "citation_count",
            "latency_ms",
            "created_at",
        ]
