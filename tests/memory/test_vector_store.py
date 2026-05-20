from unittest.mock import patch

from daemon.memory.vector_store import VectorStore


def _store_without_db() -> VectorStore:
    return VectorStore.__new__(VectorStore)


def _truth_entry():
    return {
        "active_project": "acme-api",
        "duration_min": 18,
        "activity_level": "editing",
        "started_at": "2026-05-20T10:00:00",
        "ended_at": "2026-05-20T10:18:00",
        "top_files": ["handler.py", "service.py"],
        "recent_apps": ["RandomIDE", "Terminal"],
        "summary_source": "llm",
        "summary_status": "generated",
        "task_confidence": 0.52,
        "truth_layers": {
            "observed": [
                {"kind": "commit_message", "value": "fix(memory): add truth layers"},
                {"kind": "recent_apps", "value": ["RandomIDE", "Terminal"]},
            ],
            "derived": [
                {"kind": "duration_min", "value": 18},
                {"kind": "files_count", "value": 3},
            ],
            "inferred": [
                {"kind": "probable_task", "value": "coding", "confidence": 0.52},
                {"kind": "active_project", "value": "acme-api", "source": "workspace_path"},
            ],
            "narrative": [
                {
                    "kind": "body",
                    "value": "Le travail a porté sur la provenance du journal.",
                    "source": "llm",
                    "status": "generated",
                }
            ],
        },
    }


def _indexed_call(entry):
    store = _store_without_db()
    with patch.object(store, "index_text", return_value=123) as index_text:
        result = store.index_journal_entry(entry)
    assert result == 123
    return index_text.call_args.kwargs


def test_index_journal_entry_uses_truth_layers_when_present():
    kwargs = _indexed_call(_truth_entry())

    text = kwargs["text"]
    assert "Observations :" in text
    assert "Données dérivées :" in text
    assert "Hypothèses estimées :" in text
    assert "Résumé narratif :" in text
    assert "Commit observé : fix(memory): add truth layers" in text


def test_index_journal_entry_labels_inferred_task_as_estimated():
    kwargs = _indexed_call(_truth_entry())

    text = kwargs["text"]
    assert "Tâche probable : coding (confidence: 0.52)" in text
    assert "Tâche : coding" not in text


def test_index_journal_entry_labels_body_as_narrative():
    kwargs = _indexed_call(_truth_entry())

    text = kwargs["text"]
    assert "Résumé narratif :" in text
    assert "Synthèse narrative (llm, generated) : Le travail a porté sur la provenance du journal." in text


def test_index_journal_entry_preserves_legacy_behavior_without_truth_layers():
    kwargs = _indexed_call(
        {
            "active_project": "acme-api",
            "commit_message": "fix: legacy",
            "body": "Résumé legacy.",
            "top_files": ["handler.py"],
            "probable_task": "coding",
        }
    )

    assert kwargs["text"] == "Commit : fix: legacy | Résumé legacy. | Fichiers : handler.py | Tâche : coding"
    assert kwargs["metadata"]["truth_schema"] == "legacy_flat"
    assert kwargs["metadata"]["has_truth_layers"] is False


def test_index_journal_entry_metadata_marks_truth_schema():
    kwargs = _indexed_call(_truth_entry())

    metadata = kwargs["metadata"]
    assert metadata["truth_schema"] == "truth_layers_v1"
    assert metadata["has_truth_layers"] is True
    assert metadata["source_layers"] == ["observed", "derived", "inferred", "narrative"]
    assert metadata["summary_source"] == "llm"
    assert metadata["summary_status"] == "generated"
    assert metadata["task_confidence"] == 0.52
