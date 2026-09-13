from django.db import models


class EvaluationRun(models.Model):
    """A persisted evaluation with enough configuration to reproduce it.

    ``retrieval_mode`` is the requested mode; ``retrieval_strategy`` is what
    actually ran. ``groundedness_score`` is a lexical proxy computed over
    retrieved text, not a check of answer claims against cited sources.

    Empty strings and nulls mean "not recorded". Runs created before 1.1.0
    have no stored configuration or data identity.
    """

    name = models.CharField(max_length=160)
    recall_at_k = models.FloatField(default=0)
    mean_reciprocal_rank = models.FloatField(default=0)
    expected_term_coverage = models.FloatField(default=0)
    groundedness_score = models.FloatField(default=0)
    answer_quality_score = models.FloatField(default=0)
    judged_answer_count = models.PositiveIntegerField(default=0)
    answer_judge_model = models.CharField(max_length=160, blank=True)
    average_latency_ms = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    labeled_question_count = models.PositiveIntegerField(default=0)
    coverage_question_count = models.PositiveIntegerField(default=0)
    no_results_precision = models.FloatField(default=0)
    no_results_question_count = models.PositiveIntegerField(default=0)
    # Configuration and data identity.
    retrieval_mode = models.CharField(max_length=32, blank=True, default="")
    retrieval_strategy = models.CharField(max_length=32, blank=True)
    fallback_reason = models.TextField(blank=True)
    top_k = models.PositiveIntegerField(null=True, blank=True, default=None)
    rerank = models.BooleanField(null=True, blank=True, default=None)
    embedding_model = models.CharField(max_length=160, blank=True)
    llm_model = models.CharField(max_length=160, blank=True)
    corpus_hash = models.CharField(max_length=64, blank=True)
    corpus_document_count = models.PositiveIntegerField(
        null=True, blank=True, default=None
    )
    # Source bytes alone do not identify what retrieval saw: the same bytes
    # chunked differently produce a different retrieval corpus.
    chunk_hash = models.CharField(max_length=64, blank=True)
    corpus_chunk_count = models.PositiveIntegerField(
        null=True, blank=True, default=None
    )
    question_set_hash = models.CharField(max_length=64, blank=True)
    question_set_path = models.CharField(max_length=512, blank=True)
    revision = models.CharField(max_length=64, blank=True)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name
