from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evaluations", "0002_answer_quality_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationrun",
            name="labeled_question_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="coverage_question_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
