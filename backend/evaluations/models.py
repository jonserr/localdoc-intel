from django.db import models


class EvaluationRun(models.Model):
    name = models.CharField(max_length=160)
    recall_at_k = models.FloatField(default=0)
    mean_reciprocal_rank = models.FloatField(default=0)
    citation_coverage = models.FloatField(default=0)
    groundedness_score = models.FloatField(default=0)
    answer_quality_score = models.FloatField(default=0)
    judged_answer_count = models.PositiveIntegerField(default=0)
    answer_judge_model = models.CharField(max_length=160, blank=True)
    average_latency_ms = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    labeled_question_count = models.PositiveIntegerField(default=0)
    coverage_question_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name
