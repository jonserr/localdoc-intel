"""Store unknown configuration of pre-1.1.0 evaluation runs as not recorded.

Migration 0004 filled the new configuration columns with defaults. Runs
recorded before 1.1.0 therefore reported a hybrid mode, top k 5, reranking,
and zero corpus documents, although none of these values were recorded.
Those runs are identifiable: every run recorded since 0004 stores
``retrieval_strategy_counts`` in ``config``, and older runs have an empty
``config`` and no retrieval strategy.
"""

from django.db import migrations, models


def clear_unrecorded_configuration(apps, schema_editor):
    EvaluationRun = apps.get_model("evaluations", "EvaluationRun")
    EvaluationRun.objects.filter(config={}, retrieval_strategy="").update(
        retrieval_mode="",
        top_k=None,
        rerank=None,
        corpus_document_count=None,
    )


def restore_0004_defaults(apps, schema_editor):
    EvaluationRun = apps.get_model("evaluations", "EvaluationRun")
    EvaluationRun.objects.filter(retrieval_mode="").update(retrieval_mode="hybrid")
    EvaluationRun.objects.filter(top_k__isnull=True).update(top_k=5)
    EvaluationRun.objects.filter(rerank__isnull=True).update(rerank=True)
    EvaluationRun.objects.filter(corpus_document_count__isnull=True).update(
        corpus_document_count=0
    )


class Migration(migrations.Migration):
    dependencies = [
        ("evaluations", "0004_run_configuration_and_metric_rename"),
    ]

    operations = [
        migrations.AlterField(
            model_name="evaluationrun",
            name="retrieval_mode",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AlterField(
            model_name="evaluationrun",
            name="top_k",
            field=models.PositiveIntegerField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name="evaluationrun",
            name="rerank",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name="evaluationrun",
            name="corpus_document_count",
            field=models.PositiveIntegerField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(clear_unrecorded_configuration, restore_0004_defaults),
    ]
