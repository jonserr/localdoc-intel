# Generated for LocalDoc Intel document ingestion.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="document",
            name="source_path",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddConstraint(
            model_name="document",
            constraint=models.UniqueConstraint(
                fields=("collection", "sha256"),
                name="unique_document_hash_per_collection",
            ),
        ),
    ]
