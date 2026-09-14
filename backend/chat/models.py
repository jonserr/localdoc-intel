import uuid

from django.db import models


class ChatQuery(models.Model):
    question = models.TextField()
    answer = models.TextField(blank=True)
    retrieval_mode = models.CharField(max_length=32, default="hybrid")
    retrieval_top_k = models.PositiveIntegerField(default=5)
    collection = models.CharField(max_length=160, blank=True)
    citation_count = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.question[:80]


class CollectionAnalysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cache_key = models.CharField(max_length=64, unique=True)
    question = models.TextField()
    collection = models.CharField(max_length=160, blank=True)
    target = models.TextField()
    # The reusable half of the target. Segment scanning is cached by kind,
    # so every question about the same kind shares one pass over the corpus.
    kind = models.TextField(blank=True)
    restriction = models.TextField(blank=True)
    excluded = models.JSONField(default=list)
    model = models.CharField(max_length=255)
    scope_hash = models.CharField(max_length=64)
    query = models.ForeignKey(ChatQuery, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, default="queued")
    units = models.JSONField(default=list)
    next_unit = models.PositiveIntegerField(default=0)
    document_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    missing_documents = models.JSONField(default=list)
    entries = models.JSONField(default=dict)
    unverified_count = models.PositiveIntegerField(default=0)
    skipped_units = models.PositiveIntegerField(default=0)
    cached_units = models.PositiveIntegerField(default=0)
    request_metadata = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["status"],
                condition=models.Q(status="running"),
                name="one_collection_review_running",
            ),
        ]


class CachedArtifact(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    kind = models.CharField(max_length=16, db_index=True)
    value = models.JSONField(default=dict)
    expires_at = models.DateTimeField(db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
