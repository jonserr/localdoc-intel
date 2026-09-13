"""Runs recorded before 1.1.0 report unknown configuration as not recorded."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse

from evaluations.models import EvaluationRun

BEFORE = [("evaluations", "0004_run_configuration_and_metric_rename")]
AFTER = [("evaluations", "0005_unrecorded_run_configuration")]


def migrate(targets=None):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    targets = targets or executor.loader.graph.leaf_nodes()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def configuration(run):
    return (run.retrieval_mode, run.top_k, run.rerank, run.corpus_document_count)


@pytest.mark.django_db(transaction=True)
def test_migration_clears_defaults_only_on_runs_without_recorded_configuration():
    try:
        old_apps = migrate(BEFORE)
        Run = old_apps.get_model("evaluations", "EvaluationRun")
        # 0004 fills these defaults into rows recorded before 1.1.0
        legacy = Run.objects.create(name="pre-1.1.0 run")
        assert configuration(legacy) == ("hybrid", 5, True, 0)
        recorded = Run.objects.create(
            name="1.1.0 run",
            retrieval_mode="hybrid",
            retrieval_strategy="bm25",
            top_k=5,
            rerank=True,
            corpus_document_count=0,
            config={"retrieval_strategy_counts": {"bm25": 2}},
        )

        Run = migrate(AFTER).get_model("evaluations", "EvaluationRun")

        assert configuration(Run.objects.get(pk=legacy.pk)) == ("", None, None, None)
        assert configuration(Run.objects.get(pk=recorded.pk)) == (
            "hybrid",
            5,
            True,
            0,
        )
    finally:
        migrate()


@pytest.mark.django_db
def test_api_reports_unrecorded_configuration_as_null(client):
    EvaluationRun.objects.create(name="Run without identity")

    run = client.get(reverse("evaluation-list")).json()[0]

    assert run["retrieval_mode"] == ""
    assert run["retrieval_strategy"] == ""
    assert run["top_k"] is None
    assert run["rerank"] is None
    assert run["corpus_document_count"] is None
    assert run["corpus_hash"] == ""
