# Generated for the LocalDoc Intel initial schema.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Collection",
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
                ("name", models.CharField(max_length=160, unique=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Document",
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
                ("title", models.CharField(max_length=255)),
                ("original_filename", models.CharField(max_length=255)),
                ("file_type", models.CharField(max_length=24)),
                ("sha256", models.CharField(db_index=True, max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("uploaded", "Uploaded"),
                            ("processing", "Processing"),
                            ("indexed", "Indexed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="uploaded",
                        max_length=24,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("byte_size", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_indexed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "collection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="documents.collection",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["collection", "status"],
                        name="documents_d_collect_4327e2_idx",
                    ),
                    models.Index(
                        fields=["file_type"], name="documents_d_file_ty_50bf4a_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DocumentChunk",
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
                ("chunk_index", models.PositiveIntegerField()),
                ("text", models.TextField()),
                ("page", models.PositiveIntegerField(blank=True, null=True)),
                ("start_line", models.PositiveIntegerField(blank=True, null=True)),
                ("end_line", models.PositiveIntegerField(blank=True, null=True)),
                ("byte_start", models.PositiveIntegerField(blank=True, null=True)),
                ("byte_end", models.PositiveIntegerField(blank=True, null=True)),
                ("token_count", models.PositiveIntegerField(default=0)),
                ("embedding_id", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="documents.document",
                    ),
                ),
            ],
            options={
                "ordering": ["document_id", "chunk_index"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("document", "chunk_index"),
                        name="unique_chunk_index_per_document",
                    )
                ],
            },
        ),
    ]
