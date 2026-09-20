import pytest
from django.urls import reverse
from django.utils import timezone
from documents.models import Collection, Document, DocumentChunk

from chat import analysis
from chat.models import ChatQuery, CollectionAnalysis


@pytest.fixture
def corpus():
    collection = Collection.objects.create(name="Research")
    chunks = []
    for index, text in enumerate(
        [
            "Projects: Atlas, Beacon.",
            "Projects: atlas, Comet.",
            "Projects: Delta, Ember.",
            "Projects: Foxtrot, Gemini.",
            "Projects: Harbor, Iris.",
            "Projects: Juniper, Keystone.",
        ]
    ):
        doc = Document.objects.create(
            collection=collection,
            title=f"notes-{index}.txt",
            original_filename=f"notes-{index}.txt",
            sha256=str(index) * 64,
            file_type="txt",
            status="indexed",
            chunk_count=1,
        )
        chunks.append(
            DocumentChunk.objects.create(document=doc, chunk_index=0, text=text)
        )
    return chunks


@pytest.fixture
def data():
    return {
        "question": "What projects are in the documents?",
        "collection": "Research",
        "retrieval_mode": "hybrid",
        "top_k": 2,
        "rerank": True,
        "analysis_scope": "auto",
    }


def extraction(_system, prompt, _schema, _model, _tokens, timeout=None):
    import json

    sources = json.loads(prompt)["sources"]
    return {
        "sources": [
            {
                "id": source["id"],
                "items": [
                    {"name": name.strip(), "evidence": source["text"]}
                    for name in source["text"]
                    .removeprefix("Projects: ")
                    .rstrip(".")
                    .split(",")
                ],
            }
            for source in sources
        ]
    }


@pytest.mark.django_db
def test_full_inventory_visits_sources_beyond_top_k_and_deduplicates(
    corpus, data, mocker
):
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    model = mocker.patch("chat.analysis.model_json", side_effect=extraction)
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    job, cached = analysis.start_analysis(data, "project names")
    assert not cached
    assert job.chunk_count == 6
    assert enqueue.call_count == 1
    for _ in range(3):
        analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "complete"
    assert job.next_unit == 6
    assert model.call_count == 3
    response = analysis.analysis_response(job)
    assert len(response["inventory"]) == 11
    assert "Keystone" in [e["name"] for e in response["inventory"]]
    assert response["metadata"]["retrieved_source_count"] == 6
    assert response["metadata"]["retrieval_top_k"] == 2
    assert "not a verified count" in response["answer"]
    assert len(response["citations"]) == 6
    assert job.query.answer == response["answer"]


@pytest.mark.django_db
def test_cache_reuse_and_invalidation(corpus, data, mocker):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    first, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(first.id))
    again, cached = analysis.start_analysis(data, "project names")
    assert cached and again.pk == first.pk
    assert enqueue.call_count == 1
    corpus[0].text = "Projects: New."
    corpus[0].save()
    changed, cached = analysis.start_analysis(data, "project names")
    assert not cached and changed.pk != first.pk


@pytest.mark.django_db
def test_failure_keeps_progress_and_explicit_resubmission_resumes(corpus, data, mocker):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    model = mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    model.side_effect = analysis.AnalysisError("invalid evidence")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "failed"
    assert job.next_unit == 2
    assert len(job.entries) == 3
    assert analysis.analysis_response(job)["inventory"] == []
    resumed, cached = analysis.start_analysis(data, "project names")
    assert not cached and resumed.next_unit == 2
    model.side_effect = extraction
    analysis.analyze_batch(str(job.id))
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "complete"
    assert len(job.entries) == 11


@pytest.mark.django_db
def test_missing_text_is_partial_and_other_collections_are_excluded(
    corpus, data, mocker
):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    empty = Document.objects.create(
        collection=corpus[0].document.collection, title="empty.pdf", sha256="e" * 64
    )
    other = Document.objects.create(
        collection=Collection.objects.create(name="Other"),
        title="other",
        sha256="f" * 64,
    )
    DocumentChunk.objects.create(
        document=other, chunk_index=0, text="Projects: Hidden."
    )
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    response = analysis.analysis_response(job)
    assert job.status == "partial"
    assert job.document_count == 7
    assert job.missing_documents == [empty.id]
    assert len(response["inventory"]) == 11
    assert "Review is incomplete" in response["answer"]


@pytest.mark.django_db
def test_changed_collection_during_review_is_not_complete(corpus, data, mocker):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(data, "project names")
    corpus[0].document.title = "renamed"
    corpus[0].document.save()
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "failed"
    assert "Collection changed" in job.error


@pytest.mark.django_db
def test_long_chunks_are_segmented_without_omitting_tail(corpus):
    chunk = corpus[0]
    chunk.text = "x" * (analysis.SEGMENT_CHARS * 2) + "Tail project."
    chunk.save()
    _, units, _, _ = analysis.scope_snapshot("Research")
    segments = [u for u in units if u["chunk_id"] == chunk.id]
    assert segments[0]["start"] == 0
    assert segments[-1]["end"] == len(chunk.text)
    assert all(
        b["start"] <= a["end"] for a, b in zip(segments, segments[1:], strict=False)
    )


SOURCE = [{"id": 0, "chunk_id": 1, "text": "Projects: Atlas."}]


@pytest.mark.parametrize(
    "payload",
    [
        {"sources": []},
        {"sources": [{"id": 8, "items": []}]},
        {"sources": "not-a-list"},
    ],
)
def test_unreturned_segment_cannot_count_as_reviewed(payload):
    # A segment the model did not answer for is never counted as reviewed.
    with pytest.raises(analysis.IncompleteExtraction):
        analysis.validate_extraction(payload, SOURCE)


@pytest.mark.parametrize(
    "payload",
    [
        {"sources": [{"id": 0, "items": []}, {"id": 0, "items": []}]},
        {
            "sources": [
                {"id": 0, "items": [{"name": "Invented", "evidence": "Invented"}]}
            ]
        },
        {
            "sources": [
                {
                    "id": 0,
                    "items": [{"name": "Invented", "evidence": "Projects: Atlas."}],
                }
            ]
        },
        {"sources": [{"id": 0, "items": [{"name": "   ", "evidence": "x"}]}]},
    ],
)
def test_unsupported_item_is_dropped_and_counted(payload):
    # One bad item never discards a batch whose text the model did process.
    entries, unverified = analysis.validate_extraction(payload, SOURCE)
    assert entries == []
    assert unverified == 1


def test_name_is_verified_against_source_not_the_model_quote():
    # The model's quote is advisory. The stored evidence is cut from the source,
    # so it is verbatim by construction.
    payload = {
        "sources": [
            {"id": 0, "items": [{"name": "Atlas", "evidence": "the Atlas programme"}]}
        ]
    }
    entries, unverified = analysis.validate_extraction(payload, SOURCE)
    assert unverified == 0
    assert entries[0]["name"] == "Atlas"
    assert entries[0]["evidence"] == "Projects: Atlas."


def test_name_matching_ignores_case_width_spacing_and_punctuation():
    # Deliberately looser than an exact substring: Japanese and Chinese write
    # without spaces, and OCR swaps quote, dash and fullwidth characters, which
    # previously dropped values that are plainly present in the text.
    located = analysis.locate_name
    assert located("Projects: Atlas\n Labs.", "Atlas Labs") is not None
    assert located("Projects: Atlas Labs.", "AtlasLabs") is not None
    assert located("FR L\u2019Osteria GmbH Bonn", "FR L'Osteria GmbH") is not None
    assert (
        located(
            "\u9818\u53ce\u66f8 \u4e2d\u6751\u5546\u5e97\u682a\u5f0f\u4f1a\u793e",
            "\u4e2d\u6751\u5546\u5e97 \u682a\u5f0f\u4f1a\u793e",
        )
        is not None
    )
    assert located("Rechnung \uff2e\uff52. 7 Caf\u00e9", "Nr. 7") is not None
    # A different value still does not match.
    assert located("Projects: Atlas.", "Beacon") is None
    assert located("Projects: Atlas.", "") is None


@pytest.mark.parametrize(
    "text, name",
    [
        # A decimal separator is part of the number.
        ("Dose 1.0 mg daily", "10 mg"),
        ("Total 1,250 EUR", "1250 EUR"),
        # A sign is part of the number.
        ("Refund -500 USD", "500 USD"),
        ("Adjustment +42 units", "42 units"),
        # A value may not start or end inside a longer number or identifier.
        ("Invoice 14/10/2018", "14"),
        ("Order 2026-10-01", "01"),
        ("Fee 125.00", "125"),
        # A value may not start or end inside a different word.
        ("Vendor: Wholesale Mart", "Sale Mart"),
        ("Vendor: Wholesale-Mart", "Sale Mart"),
        ("Supplier Northwind Traders", "Wind Traders"),
        ("Merchant: Burgerville", "Burger"),
        # A thousands separator and a tight identifier mark still bind.
        ("Refund INV-2026-0117 issued", "0117"),
        ("Charged 1.250,00 EUR", "250,00 EUR"),
    ],
)
def test_a_materially_different_value_is_not_verified(text, name):
    # Deliberately tighter than before: signs, decimal separators and
    # digit-bearing punctuation survive normalization, and a match must sit on
    # a value boundary. Every case here passed verification previously.
    assert analysis.locate_name(text, name) is None


@pytest.mark.parametrize(
    "text, name",
    [
        # Units and currency symbols still normalize away.
        ("Dose 10 mg daily", "10mg"),
        ("Fee $125.00 net", "125.00"),
        # Typography, width and invisible formatting still normalize away.
        ("Order 2026–10–01", "2026-10-01"),
        ("Invoice １２３", "123"),
        ("Contract 7­42", "742"),
        # A hyphen between letters is an OCR artefact, not identity.
        ("Vendor: Wal-Mart", "Wal Mart"),
        ("Vendor: Wal Mart", "Wal-Mart"),
        # A dropped mark before the value is a separator, not a word join.
        ("Projects: Atlas Labs.", "Atlas Labs"),
        ("(Atlas)", "Atlas"),
        # A clean occurrence is found even when an unclean one comes first.
        ("Wholesale Mart and Sale Mart", "Sale Mart"),
        # Label punctuation is not part of the value it introduces. A mark
        # binds to a number only when it is written tight against it.
        ("Service charge: 125.00 EUR, net", "125.00 EUR"),
        ("Line 01. Vendor: Shake Shack.", "Shake Shack"),
        ("Total = 42 units", "42 units"),
        ("Items (12) shipped", "12"),
    ],
)
def test_a_legitimate_match_still_verifies(text, name):
    assert analysis.locate_name(text, name) is not None


def test_a_verified_value_points_at_its_own_source_span():
    # The displayed value is tied to the span that supports it, not to the
    # first place its characters happen to appear.
    text = "Paid -500 USD, then 500 USD"
    span = analysis.locate_name(text, "500 USD")
    assert text[span[0] : span[1]] == "500 USD"
    assert span[0] == text.index("500 USD", 10)
    assert "500 USD" in analysis.evidence_from_source(text, span)


def test_an_ocr_variant_is_not_silently_accepted_as_equivalent():
    # OCR uncertainty in a number is a miss, not a verified equivalence.
    assert analysis.locate_name("Amount 1O0 EUR", "100 EUR") is None
    assert analysis.locate_name("Amount 100 EUR", "1OO EUR") is None


def test_located_span_points_into_the_original_text():
    text = "Kasse: FR L\u2019Osteria GmbH, Bonn"
    span = analysis.locate_name(text, "FR L'Osteria GmbH")
    assert text[span[0] : span[1]] == "FR L\u2019Osteria GmbH"
    assert "L\u2019Osteria" in analysis.evidence_from_source(text, span)


def test_group_entries_merges_legal_forms_and_trailing_qualifiers():
    def entry(name, chunk_id):
        return {"name": name, "chunk_id": chunk_id, "evidence": name}

    groups = analysis.group_entries(
        [
            entry("MADISON GmbH", 1),
            entry("MADISON Hotel GmbH", 2),
            entry("dm-drogerie markt", 3),
            entry("dm-drogerie markt GmbH + Co. KG", 4),
            entry("\u4e2d\u6751\u5546\u5e97", 5),
            entry("\u4e2d\u6751\u5546\u5e97 \u682a\u5f0f\u4f1a\u793e", 6),
            entry("Beacon Books", 7),
            entry("Beacon Coffee", 8),
        ]
    )
    by_name = {group["name"]: group for group in groups}
    assert by_name["MADISON GmbH"]["variants"] == [
        "MADISON GmbH",
        "MADISON Hotel GmbH",
    ]
    assert len(by_name["MADISON GmbH"]["sources"]) == 2
    assert by_name["dm-drogerie markt"]["variants"] == [
        "dm-drogerie markt",
        "dm-drogerie markt GmbH + Co. KG",
    ]
    assert len(by_name["\u4e2d\u6751\u5546\u5e97"]["variants"]) == 2
    # Two different merchants that merely share a first word stay separate.
    assert "Beacon Books" in by_name and "Beacon Coffee" in by_name


def test_group_entries_keeps_a_spelling_that_occurs_in_the_text():
    groups = analysis.group_entries(
        [
            {"name": "Starbucks Coffee Company", "chunk_id": 1, "evidence": "x"},
            {"name": "Starbucks", "chunk_id": 2, "evidence": "y"},
        ]
    )
    assert len(groups) == 1
    # The display name is a real variant, never a normalized reconstruction.
    assert groups[0]["name"] == "Starbucks"
    assert {hit["name"] for hit in groups[0]["sources"]} == {
        "Starbucks",
        "Starbucks Coffee Company",
    }


@pytest.mark.django_db
def test_batch_sources_are_numbered_locally(corpus, data, mocker):
    # Small local ids: a local model echoes 0..n back reliably, global unit
    # indices it does not.
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 3)
    job, _ = analysis.start_analysis(data, "project names")
    job.next_unit = 3
    sources, _ = analysis.batch_sources(job)
    assert [source["id"] for source in sources] == [0, 1, 2]


@pytest.mark.django_db
def test_single_unprocessable_segment_is_skipped_not_fatal(corpus, data, mocker):
    # The job keeps its coverage honest and still finishes.
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    mocker.patch(
        "chat.analysis.model_json",
        side_effect=analysis.IncompleteExtraction("omitted a source"),
    )
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "queued"
    assert job.next_unit == 1
    assert job.skipped_units == 1
    assert job.error == ""


@pytest.mark.django_db
def test_skipped_segments_make_the_review_partial(corpus, data, mocker):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 1)
    model = mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(data, "project names")
    for index in range(6):
        model.side_effect = (
            analysis.TruncatedOutput("cut off") if index == 0 else extraction
        )
        analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    response = analysis.analysis_response(job)
    assert job.status == "partial"
    assert job.skipped_units == 1
    assert job.next_unit == 6
    assert "could not be reviewed" in response["answer"]
    assert response["metadata"]["analysis_skipped_units"] == 1


def test_normalization_is_conservative():
    assert analysis.name_key(" ATLAS  Labs ") == analysis.name_key("atlas labs")
    assert analysis.name_key("Atlas Inc.") != analysis.name_key("Atlas")


@pytest.mark.parametrize(
    "question",
    [
        "How many vendors are in the receipts?",
        "What projects are in the documents?",
        "List the authors in the collection.",
        "Can you name all the merchants/vendors there are in the docs?",
        "Who supplies us?",
        "Which renewal dates appear in the contracts?",
        "What error codes occur in the logs?",
        "What amounts were charged on the invoices?",
    ],
)
@pytest.mark.django_db
def test_inventory_intent_is_not_receipt_specific(question, settings, mocker):
    settings.ANSWER_GENERATION_ENABLED = True
    model = mocker.patch(
        "chat.analysis.model_json",
        return_value={"operation": "inventory", "target": "requested names"},
    )
    assert analysis.inventory_target(question).target == "requested names"
    model.assert_called_once()


def test_lookup_scope_does_not_call_planner(settings, mocker):
    settings.ANSWER_GENERATION_ENABLED = True
    model = mocker.patch("chat.analysis.model_json")
    assert analysis.inventory_target("How many names?", "retrieved") is None
    model.assert_not_called()


@pytest.mark.django_db
def test_specific_document_count_can_route_to_lookup(settings, mocker):
    settings.ANSWER_GENERATION_ENABLED = True
    mocker.patch(
        "chat.analysis.model_json", return_value={"operation": "lookup", "target": ""}
    )
    assert analysis.inventory_target("How many pages does report.pdf have?") is None


@pytest.mark.django_db
def test_api_starts_and_polls_review_without_top_k_retrieval(
    client, corpus, data, mocker
):
    mocker.patch("chat.views.inventory_target", return_value="project names")
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    retrieve = mocker.patch("chat.views.retrieve")
    response = client.post(
        reverse("chat-query"),
        data={**data, "analysis_scope": "collection"},
        content_type="application/json",
    )
    assert response.status_code == 202
    result = response.json()
    assert result["metadata"]["answer_mode"] == "collection_analysis"
    assert result["metadata"]["collection_chunk_count"] == 6
    retrieve.assert_not_called()
    poll = client.get(
        reverse("chat-analysis", args=[result["metadata"]["analysis_id"]])
    )
    assert poll.status_code == 200
    assert poll.json()["metadata"]["analysis_status"] == "queued"


@pytest.mark.django_db
def test_stalled_job_is_reported_failed(corpus, data, mocker):
    from datetime import timedelta

    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    job, _ = analysis.start_analysis(data, "projects")
    CollectionAnalysis.objects.filter(pk=job.pk).update(
        updated_at=timezone.now() - timedelta(hours=1)
    )
    job.refresh_from_db()
    analysis.expire_stalled_analysis(job)
    assert job.status == "failed"
    assert "stopped making progress" in job.error


@pytest.mark.django_db
def test_transient_transport_error_is_retried(corpus, data, mocker):
    import requests

    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "TRANSIENT_BACKOFF_SECONDS", 0)
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    model = mocker.patch(
        "chat.analysis.model_json",
        side_effect=[requests.ConnectionError("reset"), extraction_payload()],
    )
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert model.call_count == 2
    assert job.status == "queued"
    assert job.error == ""
    assert job.next_unit == 2


def extraction_payload():
    return {
        "sources": [
            {"id": 0, "items": [{"name": "Atlas", "evidence": "Projects: Atlas"}]},
            {"id": 1, "items": [{"name": "Comet", "evidence": "Projects: Comet"}]},
        ]
    }


@pytest.mark.django_db
def test_batch_timeout_shrinks_instead_of_failing(corpus, data, mocker):
    import requests

    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    sleep = mocker.patch("chat.analysis.time.sleep")
    model = mocker.patch(
        "chat.analysis.model_json",
        side_effect=[
            requests.ReadTimeout("too slow"),
            {"sources": [{"id": 0, "items": [{"name": "Atlas", "evidence": "x"}]}]},
        ],
    )
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    # A timeout is never retried unchanged; it halves the batch immediately.
    assert model.call_count == 2
    sleep.assert_not_called()
    assert job.status == "queued"
    assert job.error == ""
    assert job.next_unit == 1
    assert job.skipped_units == 0
    assert len(job.entries) == 1


@pytest.mark.django_db
def test_auto_lookup_does_not_start_an_expensive_review(client, corpus, data, mocker):
    planner = mocker.patch("chat.views.inventory_target", return_value=None)
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    response = client.post(
        reverse("chat-query"),
        data={**data, "question": "Explain project planning."},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["answer_mode"] != "collection_analysis"
    planner.assert_called_once_with("Explain project planning.", "auto")
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_cancel_prevents_an_inflight_batch_from_rescheduling(corpus, data, mocker):
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    job, _ = analysis.start_analysis(data, "project names")

    def cancel_during_call(*args):
        analysis.cancel_analysis(job)
        return extraction(*args)

    mocker.patch("chat.analysis.model_json", side_effect=cancel_during_call)
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert job.next_unit == 0
    assert enqueue.call_count == 1
    assert "Review stopped" in analysis.analysis_response(job)["answer"]
    # Late error handling cannot resurrect a cancelled job either.
    analysis.fail_analysis(job, "late error")
    job.refresh_from_db()
    assert job.status == "cancelled"


@pytest.mark.django_db
def test_new_snapshot_reuses_unchanged_segments(corpus, data, mocker):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    model = mocker.patch("chat.analysis.model_json", side_effect=extraction)
    first, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(first.id))
    assert model.call_count == 1
    corpus[0].text = "Projects: Novel."
    corpus[0].save()
    second, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(second.id))
    second.refresh_from_db()
    assert second.status == "complete"
    assert second.cached_units == 5
    import json

    sent = json.loads(model.call_args.args[1])["sources"]
    assert len(sent) == 1 and sent[0]["text"] == "Projects: Novel."
    assert "Novel" in [e["name"] for e in second.entries.values()]
    assert "Atlas" not in [e["name"] for e in second.entries.values()]


@pytest.mark.django_db
def test_auto_reuses_completed_review_without_planner(client, corpus, data, mocker):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    planner = mocker.patch("chat.views.inventory_target")
    response = client.post(
        reverse("chat-query"), data=data, content_type="application/json"
    )
    assert response.json()["metadata"]["analysis_cached"] is True
    planner.assert_not_called()
    assert enqueue.call_count == 1


@pytest.mark.django_db
def test_cancel_and_resume_api_preserves_progress(client, corpus, data, mocker):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    url = reverse("chat-analysis-control", args=[job.id])
    stopped = client.post(url, {"action": "cancel"}, content_type="application/json")
    assert stopped.json()["metadata"]["analysis_status"] == "cancelled"
    resumed = client.post(url, {"action": "resume"}, content_type="application/json")
    assert resumed.json()["metadata"]["analysis_status"] == "queued"
    assert resumed.json()["metadata"]["analysis_units_processed"] == 2
    assert (
        client.get(reverse("chat-analyses-active")).json()[0]["question"]
        == data["question"]
    )


@pytest.mark.django_db
def test_reviews_do_not_run_model_batches_concurrently(corpus, data, mocker):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    deferred = mocker.patch("chat.tasks.analyze_collection_batch.apply_async")
    model = mocker.patch("chat.analysis.model_json", side_effect=extraction)
    first, _ = analysis.start_analysis(data, "projects")
    second, _ = analysis.start_analysis(
        {**data, "question": "List project names"}, "projects"
    )
    CollectionAnalysis.objects.filter(pk=first.pk).update(status="running")
    analysis.analyze_batch(str(second.id))
    second.refresh_from_db()
    assert second.status == "queued"
    model.assert_not_called()
    deferred.assert_called_once_with(args=[str(second.id)], countdown=5)
    analysis.cancel_analysis(first)
    analysis.analyze_batch(str(second.id))
    second.refresh_from_db()
    assert second.status == "complete"


@pytest.mark.django_db
def test_segment_cache_does_not_copy_names_between_segments_of_one_chunk(
    corpus, data, mocker
):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    import json

    from chat.cache import get_artifact

    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "SEGMENT_CHARS", 20)
    mocker.patch.object(analysis, "SEGMENT_OVERLAP", 0)
    corpus[0].text = "Project Atlas.      " + "Atlas: unrelated."
    corpus[0].save()

    def first_only(_system, prompt, _schema, _model, _tokens):
        return {
            "sources": [
                {"id": s["id"], "items": [{"name": "Atlas"}] if s["id"] == 0 else []}
                for s in json.loads(prompt)["sources"]
            ]
        }

    mocker.patch("chat.analysis.model_json", side_effect=first_only)
    job, _ = analysis.start_analysis(data, "project names")
    sources, _ = analysis.batch_sources(job)
    second = sources[1]
    assert second["chunk_id"] == sources[0]["chunk_id"]
    analysis.analyze_batch(str(job.id))
    assert (
        get_artifact("extraction", analysis.extraction_key(job, second))["items"] == []
    )


@pytest.mark.django_db
def test_semantic_routing_decision_is_cached(settings, mocker):
    settings.ANSWER_GENERATION_ENABLED = True
    model = mocker.patch(
        "chat.analysis.model_json", return_value={"operation": "lookup", "target": ""}
    )
    assert analysis.inventory_target("Explain onboarding.") is None
    assert analysis.inventory_target("Explain onboarding.") is None
    assert model.call_count == 1
    analysis.inventory_target("Explain deployments.")
    assert model.call_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "question",
    [
        "Can you name all the merchants/vendors there are in the docs?",
        "Who supplies us?",
        "What amounts appear in the documents?",
    ],
)
def test_auto_inventory_uses_semantic_plan_and_reviews_beyond_top_k(
    client, corpus, data, settings, mocker, question
):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    settings.ANSWER_GENERATION_ENABLED = True
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")

    def model(system, *args, **kwargs):
        if system == analysis.PLAN_INSTRUCTIONS:
            return {"operation": "inventory", "target": "project names"}
        return extraction(system, *args)

    mocker.patch("chat.analysis.model_json", side_effect=model)
    retrieve = mocker.patch("chat.views.retrieve")
    response = client.post(
        reverse("chat-query"),
        {**data, "question": question},
        content_type="application/json",
    )
    assert response.status_code == 202
    retrieve.assert_not_called()
    job_id = response.json()["metadata"]["analysis_id"]
    analysis.analyze_batch(job_id)
    result = client.get(reverse("chat-analysis", args=[job_id])).json()
    assert result["metadata"]["analysis_status"] == "complete"
    assert result["metadata"]["retrieved_source_count"] == 6
    assert len(result["inventory"]) == 11
    # The list is names only. Evidence is never serialized during polling.
    atlas = next(entry for entry in result["inventory"] if entry["name"] == "Atlas")
    assert set(atlas) == {"name"}
    assert result["citations"] == []
    # Supporting sources load on demand, and both chunks are found.
    references = client.get(
        reverse("chat-analysis-references", args=[job_id]), {"value": "Atlas"}
    ).json()
    assert len(references["citations"]) == 2
    assert len({source["chunk_id"] for source in references["citations"]}) == 2
    assert all(
        "atlas" in source["text_preview"].casefold()
        for source in references["citations"]
    )
    assert references["metadata"]["answer_mode"] == "review_references"
    assert references["inventory"] == []
    # Finished review is reused without running another scan.
    again = client.post(
        reverse("chat-query"),
        {**data, "question": question},
        content_type="application/json",
    )
    assert again.json()["metadata"]["analysis_cached"] is True
    assert enqueue.call_count == 1


def test_extraction_keeps_numeric_values_and_their_verbatim_evidence():
    sources = [
        {
            "id": 0,
            "chunk_id": 1,
            "text": "Renewal 2026-10-01. Fee $125.00. Error E104.",
            "title": "Agreement",
        }
    ]
    payload = {
        "sources": [
            {
                "id": 0,
                "items": [
                    {"name": value, "evidence": ""}
                    for value in ["2026-10-01", "$125.00", "E104"]
                ],
            }
        ]
    }
    entries, unverified = analysis.validate_extraction(payload, sources)
    assert unverified == 0
    assert [entry["name"] for entry in entries] == ["2026-10-01", "$125.00", "E104"]
    assert all(entry["name"] in entry["evidence"] for entry in entries)


@pytest.mark.django_db
def test_planning_failure_preserves_chat_fallback(client, corpus, data, mocker):
    mocker.patch(
        "chat.views.inventory_target",
        side_effect=analysis.AnalysisError("Planner unavailable"),
    )
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    response = client.post(
        reverse("chat-query"),
        {**data, "question": "What does the document say about Atlas?"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["answer_mode"] == "extractive"
    assert (
        response.json()["metadata"]["analysis_routing_error"] == "Planner unavailable"
    )
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_verified_names_are_visible_before_completion_and_after_stop(
    corpus, data, mocker
):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 2)
    names = ["Walgreens", "Amtrak", "IN-N-OUT Burger"]
    for chunk, name in zip(corpus, names, strict=False):
        chunk.text = f"Merchant: {name}."
        chunk.save()

    def model(_system, prompt, _schema, _model, _tokens):
        import json

        return {
            "sources": [
                {
                    "id": source["id"],
                    "items": [
                        {"name": name} for name in names if name in source["text"]
                    ],
                }
                for source in json.loads(prompt)["sources"]
            ]
        }

    mocker.patch("chat.analysis.model_json", side_effect=model)
    job, _ = analysis.start_analysis(data, "merchants")
    analysis.analyze_batch(str(job.pk))
    job.refresh_from_db()
    assert job.status == "queued" and job.next_unit == 2
    result = analysis.analysis_response(job)
    assert {entry["name"] for entry in result["inventory"]} == {"Walgreens", "Amtrak"}
    assert len(result["citations"]) == 2
    assert result["metadata"]["analysis_inventory_count"] == 2
    assert "incomplete" in result["answer"]
    assert all(entry["name"] in entry["evidence"] for entry in result["inventory"])
    stopped = analysis.analysis_response(analysis.cancel_analysis(job))
    assert stopped["inventory"] == result["inventory"]
    assert stopped["citations"] == result["citations"]
    assert stopped["metadata"]["analysis_status"] == "cancelled"
    assert stopped["metadata"]["analysis_batch_elapsed_seconds"] is None
    assert "Resume to continue" in stopped["answer"]


def test_compact_extraction_does_not_generate_redundant_quotes():
    item = analysis.EXTRACTION_SCHEMA["properties"]["sources"]["items"]["properties"][
        "items"
    ]["items"]
    assert item["required"] == ["name"]
    assert set(item["properties"]) == {"name"}
    sources = [{"id": 0, "chunk_id": 1, "text": "Merchant: Walgreens."}]
    entries, invalid = analysis.validate_extraction(
        {
            "sources": [
                {
                    "id": 0,
                    "items": [{"name": "Walgreens"}, {"name": "Invented merchant"}],
                }
            ]
        },
        sources,
    )
    assert invalid == 1
    assert entries == [
        {"name": "Walgreens", "chunk_id": 1, "evidence": "Merchant: Walgreens."}
    ]


@pytest.fixture
def finished_review(client, corpus, data, mocker):
    # Production runs one segment per model call. These cases are about
    # caching, coverage and concurrency, so pin a batch that covers the
    # fixture corpus in one call and keep their call counts meaningful.
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    """A completed review of the fixture corpus, with saved evidence."""
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    return job


@pytest.mark.django_db
def test_references_endpoint_requires_a_value(client, finished_review):
    response = client.get(
        reverse("chat-analysis-references", args=[str(finished_review.id)])
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_references_for_an_unknown_value_are_empty(client, finished_review):
    response = client.get(
        reverse("chat-analysis-references", args=[str(finished_review.id)]),
        {"value": "Nonexistent"},
    ).json()
    assert response["citations"] == []
    assert response["inventory"] == []
    assert 'Found 0 saved source passages for "Nonexistent"' in response["answer"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "question",
    [
        'What references contain "Atlas"?',
        "Which documents mention Atlas",
        "What sources include Atlas?",
    ],
)
def test_contextual_reference_question_uses_saved_evidence(
    client, finished_review, data, mocker, question
):
    model = mocker.patch("chat.analysis.model_json")
    before = CollectionAnalysis.objects.count()
    result = client.post(
        reverse("chat-query"),
        {**data, "question": question, "review_id": str(finished_review.id)},
        content_type="application/json",
    ).json()
    # A saved lookup calls no model and starts no new review.
    model.assert_not_called()
    assert CollectionAnalysis.objects.count() == before
    assert result["metadata"]["answer_mode"] == "review_references"
    assert len(result["citations"]) == 2
    assert result["inventory"] == []
    # It is a chat reply, so it carries its own id and measured latency.
    assert result["id"] == ChatQuery.objects.latest("created_at").id
    assert result["metadata"]["latency_ms"] >= 0
    # A reference reply is not a review, so review polling and controls skip it.
    assert "analysis_status" not in result["metadata"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "override",
    [
        {"question": 'What references contain "Nonexistent"?'},
        {"collection": "Other"},
        {"question": "Summarize the Atlas project."},
    ],
)
def test_reference_question_falls_back_when_it_cannot_be_answered_from_saved_evidence(
    client, finished_review, data, mocker, override
):
    from types import SimpleNamespace

    Collection.objects.get_or_create(name="Other")
    mocker.patch("chat.views.inventory_target", return_value=None)
    retrieve = mocker.patch("chat.views.retrieve")
    # Real objects, not Mocks. A Mock invents every attribute, so the JSON
    # renderer follows tolist() forever and the process dies.
    retrieve.return_value = SimpleNamespace(
        chunks=[], strategy="hybrid", fallback_reason=""
    )
    mocker.patch(
        "chat.views.generate_answer",
        return_value=SimpleNamespace(
            answer="No results.",
            mode="extractive",
            cached=False,
            error="",
            citation_status="not_applicable",
            cited_sources=[],
            invalid_citations=[],
        ),
    )
    payload = {
        **data,
        "question": 'What references contain "Atlas"?',
        "review_id": str(finished_review.id),
        **override,
    }
    result = client.post(
        reverse("chat-query"), payload, content_type="application/json"
    ).json()
    assert result["metadata"]["answer_mode"] != "review_references"
    retrieve.assert_called_once()


@pytest.mark.django_db
def test_changed_or_deleted_source_cannot_produce_stale_evidence(
    client, finished_review, corpus
):
    url = reverse("chat-analysis-references", args=[str(finished_review.id)])
    assert len(client.get(url, {"value": "Atlas"}).json()["citations"]) == 2
    # Evidence is re-verified against current stored text, never replayed.
    corpus[0].text = "Projects: Beacon only."
    corpus[0].save()
    assert len(client.get(url, {"value": "Atlas"}).json()["citations"]) == 1
    corpus[1].delete()
    assert client.get(url, {"value": "Atlas"}).json()["citations"] == []


@pytest.mark.django_db
def test_single_segment_is_retried_once_before_being_skipped(corpus, data, mocker):
    # One segment per call is the production default, so there is no smaller
    # batch to fall back to. One retry protects coverage without costing time
    # on the common path.
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 1)
    model = mocker.patch(
        "chat.analysis.model_json",
        side_effect=[
            analysis.IncompleteExtraction("omitted the source"),
            {"sources": [{"id": 0, "items": [{"name": "Atlas"}]}]},
        ],
    )
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert model.call_count == 2
    assert job.skipped_units == 0
    assert job.next_unit == 1
    assert [entry["name"] for entry in job.entries.values()] == ["Atlas"]


@pytest.mark.django_db
def test_single_segment_that_keeps_failing_is_skipped_not_retried_forever(
    corpus, data, mocker
):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 1)
    model = mocker.patch(
        "chat.analysis.model_json",
        side_effect=analysis.IncompleteExtraction("omitted the source"),
    )
    job, _ = analysis.start_analysis(data, "project names")
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert model.call_count == 2
    assert job.skipped_units == 1
    assert job.next_unit == 1
    assert job.status == "queued"
    assert job.error == ""


def test_numeric_values_never_absorb_longer_ones():
    # A quantity is not an identity prefix.
    groups = analysis.group_entries(
        [
            {"name": "14", "chunk_id": 1, "evidence": "14"},
            {"name": "14/10/2018 20:05. 168", "chunk_id": 2, "evidence": "x"},
            {"name": "EUR 12.29", "chunk_id": 3, "evidence": "y"},
        ]
    )
    assert len(groups) == 3


class _Reply:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": self._content}}


@pytest.mark.django_db
def test_routing_and_extraction_share_one_context_size(settings, mocker):
    # Ollama keys a resident model by context size. Mixing sizes evicted and
    # reloaded the model on every switch, which made routing time out.
    settings.ANSWER_GENERATION_ENABLED = True
    settings.COLLECTION_REVIEW_CONTEXT_TOKENS = 8192
    posted = []

    def post(url, json=None, timeout=None, **kwargs):
        posted.append((json["options"]["num_ctx"], timeout))
        return _Reply('{"operation": "lookup", "target": "x"}')

    mocker.patch("chat.analysis.requests.post", side_effect=post)
    analysis.inventory_target("List every merchant name in the documents")
    analysis.model_json(
        analysis.EXTRACTION_INSTRUCTIONS,
        "{}",
        analysis.EXTRACTION_SCHEMA,
        "model",
        256,
    )
    assert len(posted) == 2
    assert {context for context, _ in posted} == {8192}


@pytest.mark.django_db
def test_routing_fails_fast_while_a_review_batch_keeps_its_full_timeout(
    settings, mocker
):
    settings.ANSWER_GENERATION_ENABLED = True
    settings.LLM_TIMEOUT_SECONDS = 120.0
    settings.ROUTING_TIMEOUT_SECONDS = 30.0
    posted = []

    def post(url, json=None, timeout=None, **kwargs):
        posted.append(timeout)
        return _Reply('{"operation": "lookup", "target": "x"}')

    mocker.patch("chat.analysis.requests.post", side_effect=post)
    analysis.inventory_target("List every merchant name in the documents")
    assert posted == [30.0]
    analysis.model_json(
        analysis.EXTRACTION_INSTRUCTIONS,
        "{}",
        analysis.EXTRACTION_SCHEMA,
        "model",
        256,
    )
    # A review batch is background work and keeps the configured limit.
    assert posted[1] == 120.0


@pytest.mark.django_db
def test_plan_splits_a_restriction_from_the_reusable_kind(settings, mocker):
    # The kind is what gets scanned and cached. The restriction is applied later
    # to extracted values, so a narrower question reuses the same scan.
    settings.ANSWER_GENERATION_ENABLED = True
    mocker.patch(
        "chat.analysis.model_json",
        return_value={
            "operation": "inventory",
            "target": "burger restaurant vendors",
            "kind": "merchant names",
            "restriction": "is a burger restaurant",
        },
    )
    plan = analysis.inventory_target("Can you list all burger restaurant vendors?")
    assert plan.kind == "merchant names"
    assert plan.restriction == "is a burger restaurant"
    assert plan.target == "burger restaurant vendors"


def test_a_bare_target_still_works_as_a_whole_kind():
    plan = analysis.Plan.of("project names")
    assert plan.kind == "project names"
    assert plan.restriction == ""


@pytest.mark.django_db
def test_narrower_question_reuses_the_scan_of_the_same_kind(corpus, data, mocker):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    model = mocker.patch("chat.analysis.model_json", side_effect=extraction)
    broad = analysis.Plan("project names", "project names", "")
    first, _ = analysis.start_analysis(data, broad)
    analysis.analyze_batch(str(first.id))
    scans = model.call_count

    narrow = analysis.Plan("Atlas-like projects", "project names", "starts with A")
    model.side_effect = lambda *a, **k: {"matching": ["Atlas"]}
    second, _ = analysis.start_analysis(
        {**data, "question": "Which A projects?"}, narrow
    )
    analysis.analyze_batch(str(second.id))
    second.refresh_from_db()

    # No segment was read again: the extra call is the restriction filter only.
    assert second.cached_units == first.chunk_count
    assert model.call_count == scans + 1
    shown = [item["name"] for item in analysis.analysis_summary(second)["inventory"]]
    assert shown == ["Atlas"]
    assert len(second.entries) > 1


@pytest.mark.django_db
def test_restriction_is_judged_on_values_not_on_raw_text(corpus, data, mocker):
    # The failure this prevents: a review for burger vendors returning STARBUCKS
    # because a small model cannot apply the condition while reading a receipt.
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    job, _ = analysis.start_analysis(
        data, analysis.Plan("burger vendors", "merchant names", "is a burger chain")
    )
    model = mocker.patch(
        "chat.analysis.model_json",
        return_value={"matching": ["FIVE GUYS", "BURGER KING"]},
    )
    names = ["STARBUCKS", "FIVE GUYS", "dm", "BURGER KING"]
    assert analysis.restriction_matches(job, names) == {"FIVE GUYS", "BURGER KING"}
    # The verdict is cached, so a second review of the same values is free.
    assert analysis.restriction_matches(job, names) == {"FIVE GUYS", "BURGER KING"}
    model.assert_called_once()


@pytest.mark.django_db
def test_an_undecidable_restriction_keeps_values_for_a_later_verdict(
    corpus, data, mocker
):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    job, _ = analysis.start_analysis(
        data, analysis.Plan("burger vendors", "merchant names", "is a burger chain")
    )
    model = mocker.patch(
        "chat.analysis.model_json",
        side_effect=analysis.IncompleteExtraction("returned a bare list"),
    )
    names = ["STARBUCKS", "FIVE GUYS"]
    # Undecided, not "all match": the values are kept for a later batch rather
    # than being silently accepted or dropped. They are not results meanwhile.
    assert analysis.restriction_matches(job, names) is None
    assert model.call_count == 2


@pytest.mark.django_db
def test_no_restriction_means_no_model_call(corpus, data, mocker):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    job, _ = analysis.start_analysis(
        data, analysis.Plan("all merchants", "merchant names", "")
    )
    model = mocker.patch("chat.analysis.model_json")
    assert analysis.restriction_matches(job, ["STARBUCKS"]) == {"STARBUCKS"}
    model.assert_not_called()


@pytest.mark.django_db
def test_values_found_before_a_verdict_are_judged_later(corpus, data, mocker):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch.object(analysis, "BATCH_SOURCES", 12)
    mocker.patch("chat.analysis.model_json", side_effect=extraction)
    job, _ = analysis.start_analysis(
        data, analysis.Plan("A projects", "project names", "starts with A")
    )
    # A batch that ran while the restriction could not be decided.
    mocker.patch("chat.analysis.ask_restriction", return_value=None)
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.excluded == []
    assert len(job.entries) == 11

    # A later batch judges the backlog rather than leaving it unfiltered.
    mocker.patch("chat.analysis.ask_restriction", return_value={"matching": ["Atlas"]})
    CollectionAnalysis.objects.filter(pk=job.pk).update(status="queued", next_unit=0)
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    shown = [item["name"] for item in analysis.analysis_summary(job)["inventory"]]
    assert shown == ["Atlas"]
    assert len(job.excluded) == 10


@pytest.mark.django_db
def test_a_follow_up_question_carrying_a_review_id_starts_a_second_review(
    client, corpus, data, mocker
):
    # The chat page sends the previous review_id with every later question. The
    # request serializer returns it as a UUID, which a JSONField cannot store,
    # so the second submission used to fail while persisting the review.
    import json

    mocker.patch("chat.views.inventory_target", return_value="project names")
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    first = client.post(
        reverse("chat-query"),
        data={**data, "analysis_scope": "collection"},
        content_type="application/json",
    )
    assert first.status_code == 202

    second = client.post(
        reverse("chat-query"),
        data={
            **data,
            "question": "What error codes are in the documents?",
            "analysis_scope": "collection",
            "review_id": first.json()["metadata"]["analysis_id"],
        },
        content_type="application/json",
    )
    assert second.status_code == 202
    job = CollectionAnalysis.objects.get(pk=second.json()["metadata"]["analysis_id"])
    # The stored request is JSON, and the transient pointer is not part of it.
    assert "review_id" not in job.request_metadata
    assert json.loads(json.dumps(job.request_metadata)) == job.request_metadata
    assert job.request_metadata["top_k"] == data["top_k"]

    # The stored request stays usable: cancel and resume replay it.
    control = reverse("chat-analysis-control", args=[job.id])
    assert (
        client.post(
            control, {"action": "cancel"}, content_type="application/json"
        ).json()["metadata"]["analysis_status"]
        == "cancelled"
    )
    resumed = client.post(
        control, {"action": "resume"}, content_type="application/json"
    )
    assert resumed.status_code == 200
    assert resumed.json()["metadata"]["analysis_status"] == "queued"
    assert resumed.json()["metadata"]["retrieval_top_k"] == data["top_k"]


@pytest.fixture
def wide_corpus():
    """One chunk holding more values than a single filtering batch can judge."""
    collection = Collection.objects.create(name="Research")
    document = Document.objects.create(
        collection=collection,
        title="ledger.txt",
        original_filename="ledger.txt",
        sha256="a" * 64,
        file_type="txt",
        status="indexed",
        chunk_count=1,
    )
    values = ", ".join(f"Vendor{index:03d}" for index in range(45))
    return DocumentChunk.objects.create(
        document=document, chunk_index=0, text=f"Merchants: {values}."
    )


def ledger_extraction(_system, prompt, _schema, _model, _tokens, timeout=None):
    import json

    return {
        "sources": [
            {
                "id": source["id"],
                "items": [
                    {"name": value.strip()}
                    for value in source["text"]
                    .removeprefix("Merchants: ")
                    .rstrip(".")
                    .split(",")
                ],
            }
            for source in json.loads(prompt)["sources"]
        ]
    }


def chosen(*keep):
    """A filter verdict that confirms only `keep` out of each supplied batch."""
    return lambda _job, names: {"matching": [n for n in names if n in keep]}


REVIEW = analysis.Plan("chosen vendors", "merchant names", "is chosen")


@pytest.mark.django_db
def test_an_unjudged_candidate_is_never_reported_as_a_confirmed_match(
    wide_corpus, data, mocker
):
    # 45 extracted values and 40 judged per call: the last five have no verdict
    # when the final segment is read, and a verdict is what makes a result.
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    model = mocker.patch("chat.analysis.model_json", side_effect=ledger_extraction)
    mocker.patch(
        "chat.analysis.ask_restriction", side_effect=chosen("Vendor000", "Vendor044")
    )
    job, _ = analysis.start_analysis(data, REVIEW)
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()

    assert job.next_unit == len(job.units)
    assert job.status == "queued"
    pending = analysis.analysis_summary(job)
    assert pending["metadata"]["analysis_filter_total"] == 45
    assert pending["metadata"]["analysis_filter_pending"] == 5
    assert [item["name"] for item in pending["inventory"]] == ["Vendor000"]
    assert pending["metadata"]["analysis_inventory_count"] == 1
    assert "waiting for a filter verdict" in pending["answer"]

    # Filtering continues after extraction without reading any segment again.
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()
    assert job.status == "complete"
    assert model.call_count == 1
    done = analysis.analysis_summary(job)
    assert done["metadata"]["analysis_filter_pending"] == 0
    assert [item["name"] for item in done["inventory"]] == ["Vendor000", "Vendor044"]
    assert len(job.excluded) == 43


@pytest.mark.django_db
def test_a_saved_review_is_reusable_only_once_every_value_is_judged(
    wide_corpus, data, mocker
):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=ledger_extraction)
    mocker.patch(
        "chat.analysis.ask_restriction", side_effect=chosen("Vendor000", "Vendor044")
    )
    job, _ = analysis.start_analysis(data, REVIEW)
    analysis.analyze_batch(str(job.id))
    # A review with an open filter backlog is not a finished review.
    assert analysis.completed_analysis(data) is None

    analysis.analyze_batch(str(job.id))
    saved = analysis.completed_analysis(data)
    assert saved is not None and saved.pk == job.pk
    cached = analysis.analysis_summary(saved, cached=True)
    assert cached["metadata"]["analysis_cached"] is True
    assert cached["metadata"]["analysis_filter_pending"] == 0
    assert [item["name"] for item in cached["inventory"]] == ["Vendor000", "Vendor044"]


@pytest.mark.django_db
def test_an_undecidable_filter_fails_the_review_and_keeps_its_candidates(
    wide_corpus, data, mocker
):
    mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=ledger_extraction)
    mocker.patch("chat.analysis.ask_restriction", return_value=None)
    job, _ = analysis.start_analysis(data, REVIEW)
    for _ in range(analysis.FILTER_FAILURE_LIMIT):
        analysis.analyze_batch(str(job.id))
    job.refresh_from_db()

    # Bounded: the review stops requeueing and says what it could not decide.
    assert job.status == "failed"
    assert job.filter_failures == analysis.FILTER_FAILURE_LIMIT
    assert "Could not decide the filter for 45 extracted values" in job.error
    assert len(job.entries) == 45
    assert job.excluded == []
    failed = analysis.analysis_summary(job)
    assert failed["inventory"] == []
    assert "Review failed" in failed["answer"]

    # Recovery: a resubmission judges the kept candidates and reads no text.
    mocker.patch("chat.analysis.ask_restriction", side_effect=chosen("Vendor007"))
    resumed, cached = analysis.start_analysis(data, REVIEW)
    assert not cached
    assert resumed.pk == job.pk
    assert resumed.filter_failures == 0
    analysis.analyze_batch(str(resumed.id))
    analysis.analyze_batch(str(resumed.id))
    resumed.refresh_from_db()
    assert resumed.status == "complete"
    recovered = analysis.analysis_summary(resumed)
    assert [item["name"] for item in recovered["inventory"]] == ["Vendor007"]
    assert recovered["metadata"]["analysis_filter_pending"] == 0


@pytest.mark.django_db
def test_cancelling_during_filtering_persists_nothing_and_does_not_requeue(
    wide_corpus, data, mocker
):
    enqueue = mocker.patch("chat.tasks.analyze_collection_batch.delay")
    mocker.patch("chat.analysis.model_json", side_effect=ledger_extraction)
    job, _ = analysis.start_analysis(data, REVIEW)

    def cancel_during_filtering(current, names):
        analysis.cancel_analysis(current)
        return {"matching": list(names)}

    mocker.patch("chat.analysis.ask_restriction", side_effect=cancel_during_filtering)
    analysis.analyze_batch(str(job.id))
    job.refresh_from_db()

    assert job.status == "cancelled"
    assert job.next_unit == 0
    assert job.entries == {}
    assert enqueue.call_count == 1
    assert analysis.analysis_summary(job)["inventory"] == []
