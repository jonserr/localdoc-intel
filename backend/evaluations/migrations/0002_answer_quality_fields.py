from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evaluations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationrun",
            name="answer_quality_score",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="judged_answer_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="answer_judge_model",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
