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
