"""Rename citation_coverage and record reproducibility configuration.

"Citation coverage" measured expected terms in retrieved text, not citation
accuracy, so it becomes expected_term_coverage. The new fields capture the
configuration and data identity a run needs to be reproducible.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evaluations", "0003_labeled_question_counts"),
    ]

    operations = [
        migrations.RenameField(
            model_name="evaluationrun",
            old_name="citation_coverage",
            new_name="expected_term_coverage",
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="no_results_precision",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="no_results_question_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="retrieval_mode",
            field=models.CharField(default="hybrid", max_length=32),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="retrieval_strategy",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="fallback_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="top_k",
            field=models.PositiveIntegerField(default=5),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="rerank",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="embedding_model",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="llm_model",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="corpus_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="corpus_document_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="question_set_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="question_set_path",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="revision",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="config",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
