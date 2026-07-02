# Generated for the LocalDoc Intel initial schema.

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ChatQuery",
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
                ("question", models.TextField()),
                ("answer", models.TextField(blank=True)),
                ("retrieval_mode", models.CharField(default="hybrid", max_length=32)),
                ("retrieval_top_k", models.PositiveIntegerField(default=5)),
                ("collection", models.CharField(blank=True, max_length=160)),
                ("citation_count", models.PositiveIntegerField(default=0)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
