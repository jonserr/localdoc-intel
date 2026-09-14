"""Bounded, resumable batches for on-demand collection review."""

from celery import shared_task


@shared_task
def analyze_collection_batch(job_id: str) -> None:
    from .analysis import analyze_batch

    analyze_batch(job_id)
