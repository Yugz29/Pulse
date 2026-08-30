import json
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

from daemon_v2.outbox_worker import (
    HttpResult,
    MAX_DELIVERY_ATTEMPTS,
    OutboxWorker,
    TemporaryDeliveryError,
)
from daemon_v2.producer_outbox import (
    ProducerOutbox,
    build_git_commit_payload,
    build_terminal_payload,
    enqueue_git_commit_input,
    enqueue_json_input,
    enqueue_terminal_input,
    main,
)


def canonical_payload(event_id: str, *, path: str = "/project/main.py") -> str:
    return json.dumps(
        {
            "event_id": event_id,
            "schema_version": 1,
            "type": "file_changed",
            "producer": {
                "name": "pulse-test",
                "version": "1.0",
                "instance_id": "outbox-tests",
            },
            "occurred_at": "2026-07-23T14:32:10+02:00",
            "details": {
                "path": path,
                "event": "modified",
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def ack(event_id: str, *, status: int = 201) -> HttpResult:
    return HttpResult(
        status=status,
        body=json.dumps({"accepted": True, "event_id": event_id}),
    )


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def read_pending(database, event_id):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT payload_json, attempts, last_error
            FROM events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()


def read_dead_letter(database, event_id):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT payload_json, error, http_status, response_body
            FROM dead_letters
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()


def test_unavailable_core_keeps_event_then_sends_when_core_returns(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    payload = canonical_payload("event-recovery")
    outbox.enqueue_payload(payload)
    clock = Clock()
    available = False

    def sender(raw):
        if not available:
            raise TemporaryDeliveryError("connection refused")
        assert raw == payload
        return ack("event-recovery")

    worker = OutboxWorker(outbox, sender=sender, now=clock)
    assert worker.process_one() == "retry"
    pending = read_pending(database, "event-recovery")
    assert pending[0] == payload
    assert pending[1] == 1

    available = True
    clock.advance(1)
    assert worker.process_one() == "sent"
    assert outbox.counts() == (0, 0)


def test_success_and_duplicate_ack_delete_event(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue_payload(canonical_payload("first"))
    worker = OutboxWorker(outbox, sender=lambda _: ack("first", status=201))

    assert worker.process_one() == "sent"
    assert outbox.counts() == (0, 0)

    outbox.enqueue_payload(canonical_payload("duplicate"))
    worker = OutboxWorker(outbox, sender=lambda _: ack("duplicate", status=200))
    assert worker.process_one() == "sent"
    assert outbox.counts() == (0, 0)


def test_toxic_event_expires_after_retry_limit_and_unblocks_queue(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    toxic = canonical_payload("toxic")
    healthy = canonical_payload("healthy", path="/project/other.py")
    outbox.enqueue_payload(toxic, created_at="2026-07-23T12:00:00+00:00")
    outbox.enqueue_payload(healthy, created_at="2026-07-23T12:00:01+00:00")
    clock = Clock()

    def sender(raw):
        if raw == toxic:
            return HttpResult(500, "boom")
        return ack("healthy")

    worker = OutboxWorker(outbox, sender=sender, now=clock)
    outcomes = []
    for _ in range(MAX_DELIVERY_ATTEMPTS):
        outcomes.append(worker.process_one())
        clock.advance(600)  # au-delà du backoff maximal (300 s)

    assert outcomes[:-1] == ["retry"] * (MAX_DELIVERY_ATTEMPTS - 1)
    assert outcomes[-1] == "dead-letter"
    dead = read_dead_letter(database, "toxic")
    assert dead is not None
    assert "retry limit reached" in dead[1]
    assert dead[2] == 500

    # La file n'est plus bloquée : l'événement suivant part immédiatement.
    assert worker.process_one() == "sent"
    assert outbox.counts() == (0, 1)


def test_network_errors_never_expire_events(tmp_path):
    # Un daemon éteint (connexion refusée) n'est PAS un événement toxique :
    # l'outbox promet de survivre à l'indisponibilité du consommateur, donc
    # les erreurs réseau ne comptent jamais vers le plafond de tentatives.
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("unreachable"))
    clock = Clock()

    def sender(raw):
        raise TemporaryDeliveryError("connection refused")

    worker = OutboxWorker(outbox, sender=sender, now=clock)
    for _ in range(MAX_DELIVERY_ATTEMPTS + 5):
        assert worker.process_one() == "retry"
        clock.advance(600)

    assert read_dead_letter(database, "unreachable") is None
    pending = read_pending(database, "unreachable")
    assert pending is not None
    assert pending[1] == MAX_DELIVERY_ATTEMPTS + 5

    # Le daemon revient : l'événement est livré normalement.
    worker = OutboxWorker(outbox, sender=lambda _: ack("unreachable"), now=clock)
    assert worker.process_one() == "sent"
    assert outbox.counts() == (0, 0)


def test_server_204_deletes_event_without_dead_letter(tmp_path):
    # 204 = livré-et-ignoré volontairement par le serveur (commande filtrée) :
    # un succès, pas un échec — la dead-letter reste un signal d'erreur pur.
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("filtered"))
    worker = OutboxWorker(outbox, sender=lambda _: HttpResult(204, ""))

    assert worker.process_one() == "ignored"
    assert outbox.counts() == (0, 0)


def test_replayed_dead_letter_overwrites_previous_row(tmp_path):
    # Un événement rejoué qui échoue à nouveau doit ÉCRASER sa dead-letter
    # précédente, pas lever IntegrityError (crash loop du worker).
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    for attempt in range(2):
        outbox.enqueue_payload(canonical_payload("replayed"))
        worker = OutboxWorker(
            outbox,
            sender=lambda _: HttpResult(400, "bad request"),
        )
        assert worker.process_one() == "dead-letter"
    assert outbox.counts() == (0, 1)


def test_replay_dead_letter_restarts_a_fresh_delivery_cycle(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("failed"))
    pending = outbox.oldest()
    assert pending is not None
    outbox.move_to_dead_letter(
        pending,
        error="HTTP 400",
        http_status=400,
        response_body="bad request",
        failed_at=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )
    assert outbox.counts() == (0, 1)

    assert outbox.replay_dead_letters(event_id="failed") == 1

    assert outbox.counts() == (1, 0)
    payload_json, attempts, last_error = read_pending(database, "failed")
    assert payload_json == canonical_payload("failed")
    assert attempts == 0
    assert last_error is None
    worker = OutboxWorker(outbox, sender=lambda _: ack("failed"))
    assert worker.process_one() == "sent"
    assert outbox.counts() == (0, 0)


def test_replay_then_refail_then_replay_again_is_safe(tmp_path):
    # Cycle complet replay → re-échec → replay : la dead-letter est écrasée
    # (INSERT OR REPLACE) puis rejouable à nouveau, sans perte de payload.
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("cycling"))
    for _ in range(2):
        worker = OutboxWorker(
            outbox,
            sender=lambda _: HttpResult(400, "bad request"),
        )
        assert worker.process_one() == "dead-letter"
        assert outbox.counts() == (0, 1)
        assert outbox.replay_dead_letters(event_id="cycling") == 1
        assert outbox.counts() == (1, 0)
    payload_json, attempts, _ = read_pending(database, "cycling")
    assert payload_json == canonical_payload("cycling")
    assert attempts == 0


def test_replay_by_http_status_leaves_other_failures_dead(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    for event_id, status in (("airplay", 403), ("invalid", 400)):
        outbox.enqueue_payload(app_activated_payload(event_id))
        pending = outbox.oldest()
        assert pending is not None
        outbox.move_to_dead_letter(
            pending,
            error=f"HTTP {status}",
            http_status=status,
            response_body="",
            failed_at=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        )

    assert outbox.replay_dead_letters(http_status=403) == 1

    assert outbox.counts() == (1, 1)
    assert read_pending(database, "airplay") is not None
    assert read_dead_letter(database, "invalid") is not None


def test_replayed_event_joins_the_fifo_tail(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("boom"))
    pending = outbox.oldest()
    assert pending is not None
    outbox.move_to_dead_letter(
        pending,
        error="HTTP 400",
        http_status=400,
        response_body="",
        failed_at=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )
    # Enfilé AVANT le replay : doit rester en tête de file après.
    outbox.enqueue_payload(
        canonical_payload("first"),
        created_at="2026-07-23T10:00:00+00:00",
    )

    assert outbox.replay_dead_letters(event_id="boom") == 1

    assert outbox.counts() == (2, 0)
    assert outbox.oldest().event_id == "first"


def test_replay_already_pending_event_drops_stale_dead_letter(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("dup"))
    pending = outbox.oldest()
    assert pending is not None
    outbox.move_to_dead_letter(
        pending,
        error="HTTP 400",
        http_status=400,
        response_body="",
        failed_at=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )
    # Re-enfilé pendant que la dead-letter existe encore : les deux tables
    # portent le même event_id.
    outbox.enqueue_payload(canonical_payload("dup"))

    assert outbox.replay_dead_letters(event_id="dup") == 1

    assert outbox.counts() == (1, 0)
    assert read_dead_letter(database, "dup") is None


def test_replay_rejects_conflicting_or_empty_selectors(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    with pytest.raises(ValueError):
        outbox.replay_dead_letters(event_id="x", http_status=400)
    with pytest.raises(ValueError):
        outbox.replay_dead_letters(event_id="   ")


def test_git_commit_payload_redacts_message(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    payload = build_git_commit_payload(
        outbox,
        commit_hash="abc1234",
        repository="Pulse",
        git_root="/project/Pulse",
        branch="main",
        message="rotate key: old was AKIAIOSFODNN7EXAMPLE",
        occurred_at="2026-07-23T14:32:10+02:00",
    )
    assert "AKIA" not in payload
    assert "[REDACTED]" in payload


def test_concurrent_first_instance_id_is_single_valued(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    results = []

    def worker():
        results.append(ProducerOutbox(database).producer_instance_id())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 4
    assert len(set(results)) == 1


def test_conflict_and_bad_request_move_to_dead_letter(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("conflict"))
    worker = OutboxWorker(
        outbox,
        sender=lambda _: HttpResult(409, '{"error":"conflict"}'),
    )

    assert worker.process_one() == "dead-letter"
    conflict = read_dead_letter(database, "conflict")
    assert conflict[2] == 409
    assert canonical_payload("conflict") == conflict[0]

    outbox.enqueue_payload(canonical_payload("invalid"))
    worker = OutboxWorker(
        outbox,
        sender=lambda _: HttpResult(400, '{"error":"invalid"}'),
    )
    assert worker.process_one() == "dead-letter"
    assert read_dead_letter(database, "invalid")[2] == 400
    assert outbox.counts() == (0, 2)


def test_server_error_and_timeout_retry_without_changing_payload(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    original = canonical_payload("server-error")
    outbox.enqueue_payload(original)
    clock = Clock()
    worker = OutboxWorker(
        outbox,
        sender=lambda _: HttpResult(500, "temporary"),
        now=clock,
    )

    assert worker.process_one() == "retry"
    row = read_pending(database, "server-error")
    assert row[0] == original
    assert row[1] == 1

    outbox.enqueue_payload(canonical_payload("timeout"))
    # FIFO deliberately keeps the second event behind the first retry.
    clock.advance(1)
    worker = OutboxWorker(
        outbox,
        sender=lambda _: ack("server-error"),
        now=clock,
    )
    assert worker.process_one() == "sent"

    def timeout_sender(_):
        raise TimeoutError("timed out")

    worker = OutboxWorker(outbox, sender=timeout_sender, now=clock)
    assert worker.process_one() == "retry"
    timeout_row = read_pending(database, "timeout")
    assert timeout_row[1] == 1
    assert "timed out" in timeout_row[2]


def test_protocol_errors_dead_letter_even_on_2xx(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    # 204 n'est plus un cas d'erreur : livré-et-ignoré, testé séparément
    # dans test_server_204_deletes_event_without_dead_letter.
    cases = [
        ("invalid-json", HttpResult(201, "not-json")),
        ("not-accepted", HttpResult(201, '{"accepted":false,"event_id":"not-accepted"}')),
        ("wrong-id", HttpResult(200, '{"accepted":true,"event_id":"other"}')),
    ]

    for event_id, result in cases:
        outbox.enqueue_payload(canonical_payload(event_id))
        worker = OutboxWorker(outbox, sender=lambda _, response=result: response)
        assert worker.process_one() == "dead-letter"

    assert outbox.counts() == (0, 3)


def test_multiple_events_are_delivered_fifo(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    for index in range(3):
        outbox.enqueue_payload(
            canonical_payload(f"event-{index}"),
            created_at=f"2026-07-23T12:00:0{index}+00:00",
        )
    delivered = []

    def sender(raw):
        event_id = json.loads(raw)["event_id"]
        delivered.append(event_id)
        return ack(event_id)

    worker = OutboxWorker(outbox, sender=sender)
    assert [worker.process_one() for _ in range(3)] == ["sent", "sent", "sent"]
    assert delivered == ["event-0", "event-1", "event-2"]


def test_pending_event_survives_outbox_and_worker_restart(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    first_outbox = ProducerOutbox(database)
    payload = canonical_payload("after-restart")
    first_outbox.enqueue_payload(payload)

    restarted_outbox = ProducerOutbox(database)
    restarted_worker = OutboxWorker(
        restarted_outbox,
        sender=lambda raw: ack(json.loads(raw)["event_id"]),
    )

    assert restarted_worker.process_one() == "sent"
    assert restarted_outbox.counts() == (0, 0)


def test_terminal_payload_is_redacted_before_exact_json_is_enqueued(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    raw_secret = "super-secret-value"
    raw_input = json.dumps(
        {
            "command": f"deploy --token {raw_secret}",
            "cwd": "/project",
            "exit_code": 0,
            "started_at": "2026-07-23T14:31:00+02:00",
            "finished_at": "2026-07-23T14:32:00+02:00",
        }
    )

    event_id = enqueue_terminal_input(outbox, raw_input)
    pending = outbox.oldest()

    assert event_id
    assert pending is not None
    assert raw_secret not in pending.payload_json
    assert "[REDACTED]" in pending.payload_json
    payload = json.loads(pending.payload_json)
    assert payload["producer"]["name"] == "pulse-zsh"
    assert payload["producer"]["version"] == "1.0"
    assert payload["producer"]["instance_id"]
    assert payload["event_id"] == event_id


def test_git_commit_payload_is_enqueued_regardless_of_client(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    raw_input = json.dumps(
        {
            "commit_hash": "abc1234def5678",
            "repository": "Pulse_Core",
            "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
            "branch": "main",
            "message": "Add git commit events\n\nCloses the VS Code gap.",
            "occurred_at": "2026-07-23T14:32:00+02:00",
            "files_changed": 3,
            "insertions": 42,
            "deletions": 5,
        }
    )

    event_id = enqueue_git_commit_input(outbox, raw_input)
    pending = outbox.oldest()

    assert event_id
    assert pending is not None
    payload = json.loads(pending.payload_json)
    assert payload["type"] == "git_commit"
    assert payload["event_id"] == event_id
    assert payload["producer"]["name"] == "pulse-git-hook"
    assert payload["details"] == {
        "commit_hash": "abc1234def5678",
        "repository": "Pulse_Core",
        "git_root": "/Users/yugz/Projets/Pulse/Pulse_Core",
        "branch": "main",
        "message": "Add git commit events\n\nCloses the VS Code gap.",
        "files_changed": 3,
        "insertions": 42,
        "deletions": 5,
    }


def test_git_commit_payload_omits_absent_optional_stats(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    raw_input = json.dumps(
        {
            "commit_hash": "abc1234def5678",
            "repository": "Pulse_Core",
            "git_root": "/project",
            "branch": "main",
            "message": "Fix typo",
            "occurred_at": "2026-07-23T14:32:00+02:00",
        }
    )

    event_id = enqueue_git_commit_input(outbox, raw_input)
    payload = json.loads(outbox.oldest().payload_json)

    assert event_id
    assert "files_changed" not in payload["details"]
    assert "insertions" not in payload["details"]
    assert "deletions" not in payload["details"]


def test_git_commit_input_rejects_missing_fields(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    raw_input = json.dumps(
        {
            "commit_hash": "abc1234def5678",
            "repository": "Pulse_Core",
            "git_root": "/project",
            "branch": "main",
            # message intentionally omitted
            "occurred_at": "2026-07-23T14:32:00+02:00",
        }
    )

    with pytest.raises(ValueError):
        enqueue_git_commit_input(outbox, raw_input)


def test_enqueue_git_commit_cli_reads_stdin_and_enqueues(tmp_path, monkeypatch, capsys):
    database = tmp_path / "outbox.sqlite3"
    raw_input = json.dumps(
        {
            "commit_hash": "abc1234def5678",
            "repository": "Pulse_Core",
            "git_root": "/project",
            "branch": "main",
            "message": "Fix typo",
            "occurred_at": "2026-07-23T14:32:00+02:00",
        }
    )
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(raw_input))
    monkeypatch.setattr(
        sys,
        "argv",
        ["producer_outbox", "--database", str(database), "enqueue-git-commit"],
    )

    main()

    event_id = capsys.readouterr().out.strip()
    assert event_id
    outbox = ProducerOutbox(database)
    pending = outbox.oldest()
    assert pending is not None
    assert json.loads(pending.payload_json)["type"] == "git_commit"


def test_producer_instance_id_is_stable_across_restarts(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    first = ProducerOutbox(database).producer_instance_id()
    second = ProducerOutbox(database).producer_instance_id()

    assert first
    assert second == first


def test_status_cli_reports_outbox_and_dead_letter_counts(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("PULSE_CORE_PORT", "8765")
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("pending"))
    dead = outbox.oldest()
    assert dead is not None
    outbox.move_to_dead_letter(
        dead,
        error="test",
        http_status=400,
        response_body="bad",
        failed_at=datetime.now(timezone.utc),
    )
    outbox.enqueue_payload(canonical_payload("still-pending"))

    monkeypatch.setattr(
        "sys.argv",
        ["producer_outbox", "--database", str(database), "status"],
    )
    main()

    assert capsys.readouterr().out == (
        "Outbox\n"
        "1 événement\n"
        "Dead-letter\n"
        "1 événement\n"
        "Pending: 1\n"
        "Dead-letter: 1\n"
        f"Outbox path: {database}\n"
        "Worker endpoint: http://127.0.0.1:8765/activities\n"
    )


def test_build_terminal_payload_does_not_regenerate_fields_after_enqueue(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    payload = build_terminal_payload(
        outbox,
        command="pytest -q",
        cwd="/project",
        exit_code=0,
        started_at="2026-07-23T14:31:00+02:00",
        finished_at="2026-07-23T14:32:00+02:00",
    )
    assert payload is not None
    outbox.enqueue_payload(payload)

    sent = []
    worker = OutboxWorker(
        outbox,
        sender=lambda raw: sent.append(raw) or ack(json.loads(raw)["event_id"]),
    )
    assert worker.process_one() == "sent"
    assert sent == [payload]


def app_activated_payload(event_id="app-event"):
    return json.dumps(
        {
            "event_id": event_id,
            "schema_version": 1,
            "type": "app_activated",
            "producer": {
                "name": "pulse-macos-application-observer",
                "version": "1",
                "instance_id": "stable-observer",
            },
            "occurred_at": "2026-07-23T16:00:00.000Z",
            "details": {
                "app": "Visual Studio Code",
                "bundle_id": "com.microsoft.VSCode",
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def run_outbox_cli(database, command, raw_input, *, extra_arguments=None):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "daemon_v2.producer_outbox",
            "--database",
            str(database),
            command,
            *(extra_arguments or []),
        ],
        cwd=str(__file__.rsplit("/tests_v2/", 1)[0]),
        input=raw_input,
        capture_output=True,
        text=True,
        check=False,
    )


def test_enqueue_json_validates_and_persists_exact_canonical_json(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    raw = app_activated_payload("exact-app-event")

    event_id = enqueue_json_input(outbox, raw)
    pending = outbox.oldest()

    assert event_id == "exact-app-event"
    assert pending is not None
    assert pending.event_id == "exact-app-event"
    assert pending.payload_json == raw


def test_enqueue_json_rejects_invalid_and_malformed_payloads(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    invalid = json.dumps(
        {
            "event_id": "invalid",
            "schema_version": 1,
            "type": "app_activated",
            "occurred_at": "2026-07-23T16:00:00Z",
            "details": {"app": "Terminal"},
        }
    )

    invalid_result = run_outbox_cli(database, "enqueue-json", invalid)
    malformed_result = run_outbox_cli(database, "enqueue-json", "{broken")

    assert invalid_result.returncode != 0
    assert "missing canonical fields: producer" in invalid_result.stderr
    assert malformed_result.returncode != 0
    assert "Pulse outbox:" in malformed_result.stderr
    assert ProducerOutbox(database).counts() == (0, 0)


def test_enqueue_json_cli_success_code_and_no_http_attempt(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "outbox.sqlite3"
    raw = app_activated_payload("cli-app-event")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("enqueue-json must never use HTTP")
        ),
    )

    result = run_outbox_cli(database, "enqueue-json", raw)

    assert result.returncode == 0
    assert result.stdout.strip() == "cli-app-event"
    pending = ProducerOutbox(database).oldest()
    assert pending is not None
    assert pending.payload_json == raw


def test_instance_id_cli_is_stable_and_non_empty(tmp_path):
    database = tmp_path / "outbox.sqlite3"

    first = run_outbox_cli(database, "instance-id", "")
    second = run_outbox_cli(database, "instance-id", "")

    assert first.returncode == second.returncode == 0
    assert first.stdout.strip()
    assert second.stdout.strip() == first.stdout.strip()


def test_inspect_dead_letter_cli_reports_recent_events_without_mutation(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    for event_id, status in (
        ("older", 400),
        ("newer", 403),
    ):
        outbox.enqueue_payload(
            app_activated_payload(event_id),
            created_at=f"2026-07-23T16:00:0{status % 10}+00:00",
        )
        pending = outbox.oldest()
        assert pending is not None
        outbox.move_to_dead_letter(
            pending,
            error=f"unexpected HTTP {status}",
            http_status=status,
            response_body="",
            failed_at=datetime(
                2026,
                7,
                23,
                16,
                0,
                status % 10,
                tzinfo=timezone.utc,
            ),
        )

    result = run_outbox_cli(
        database,
        "inspect-dead-letter",
        "",
        extra_arguments=["--limit", "1"],
    )

    assert result.returncode == 0
    inspected = json.loads(result.stdout)
    assert inspected == [
        {
            "event_id": "newer",
            "type": "app_activated",
            "last_error": "unexpected HTTP 403",
            "http_status": 403,
            "payload_json": app_activated_payload("newer"),
        }
    ]
    assert outbox.counts() == (0, 2)


def test_clear_dead_letter_by_http_status_preserves_pending_and_other_failures(
    tmp_path,
):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    for event_id, status in (("airplay", 403), ("invalid", 400)):
        outbox.enqueue_payload(app_activated_payload(event_id))
        pending = outbox.oldest()
        assert pending is not None
        outbox.move_to_dead_letter(
            pending,
            error=f"HTTP {status}",
            http_status=status,
            response_body="",
            failed_at=datetime.now(timezone.utc),
        )
    outbox.enqueue_payload(app_activated_payload("still-pending"))

    result = run_outbox_cli(
        database,
        "clear-dead-letter",
        "",
        extra_arguments=["--http-status", "403"],
    )

    assert result.returncode == 0
    assert result.stdout == "Deleted dead-letters: 1\n"
    assert outbox.counts() == (1, 1)
    assert read_dead_letter(database, "airplay") is None
    assert read_dead_letter(database, "invalid") is not None
    assert outbox.oldest().event_id == "still-pending"


def test_replay_dead_letter_cli_moves_event_back_to_pending(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(app_activated_payload("boom"))
    pending = outbox.oldest()
    assert pending is not None
    outbox.move_to_dead_letter(
        pending,
        error="HTTP 400",
        http_status=400,
        response_body="",
        failed_at=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )

    result = run_outbox_cli(
        database,
        "replay-dead-letter",
        "",
        extra_arguments=["--event-id", "boom"],
    )

    assert result.returncode == 0
    assert result.stdout == "Replayed dead-letters: 1\n"
    assert outbox.counts() == (1, 0)


def test_replay_dead_letter_cli_requires_an_explicit_selection(tmp_path):
    result = run_outbox_cli(tmp_path / "outbox.sqlite3", "replay-dead-letter", "")

    assert result.returncode == 2
    assert "required" in result.stderr


def test_clear_all_dead_letters_is_explicit_and_reports_zero_when_empty(tmp_path):
    database = tmp_path / "outbox.sqlite3"

    result = run_outbox_cli(
        database,
        "clear-dead-letter",
        "",
        extra_arguments=["--all"],
    )

    assert result.returncode == 0
    assert result.stdout == "Deleted dead-letters: 0\n"
    assert ProducerOutbox(database).counts() == (0, 0)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--http-status", "99"],
        ["--http-status", "403", "--all"],
    ],
)
def test_clear_dead_letter_cli_validates_selection(tmp_path, arguments):
    result = run_outbox_cli(
        tmp_path / "outbox.sqlite3",
        "clear-dead-letter",
        "",
        extra_arguments=arguments,
    )

    assert result.returncode != 0


def test_outbox_uses_wal_and_survives_concurrent_enqueues(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def enqueue_batch(prefix):
        for index in range(10):
            outbox.enqueue_payload(
                canonical_payload(f"{prefix}-{index}", path=f"/p/{prefix}/{index}.py")
            )

    threads = [
        threading.Thread(target=enqueue_batch, args=(name,))
        for name in ("zsh", "git-hook")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outbox.counts() == (20, 0)
