# Generated for the LocalDoc Intel initial schema.

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="EvaluationRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("recall_at_k", models.FloatField(default=0)),
                ("mean_reciprocal_rank", models.FloatField(default=0)),
                ("citation_coverage", models.FloatField(default=0)),
                ("groundedness_score", models.FloatField(default=0)),
                ("average_latency_ms", models.PositiveIntegerField(default=0)),
                ("question_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
