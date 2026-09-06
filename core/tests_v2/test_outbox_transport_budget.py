"""Le budget d'échecs HTTP de l'outbox ne compte pas les déconnexions
(audit 2026-09-06, défaut 6).

Politique annoncée : les erreurs de connexion sont réessayées indéfiniment,
seules les réponses HTTP réessayables (408, 429, 5xx) répétées mènent en
dead-letter. Un seul compteur `attempts` servait aux deux : une longue
coupure réseau suivie d'un premier 503 partait en dead-letter sur-le-champ.
"""

import sqlite3

from test_producer_outbox import Clock, ack, canonical_payload, read_dead_letter, read_pending

from daemon_v2.outbox_worker import (
    MAX_DELIVERY_ATTEMPTS,
    HttpResult,
    OutboxWorker,
    TemporaryDeliveryError,
)
from daemon_v2.producer_outbox import ProducerOutbox


def read_http_attempts(database, event_id):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT http_attempts FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()[0]


class Script:
    """Un sender qui rejoue une liste d'issues : exception ou HttpResult."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, raw):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _drive(worker, clock, count):
    outcomes = []
    for _ in range(count):
        outcomes.append(worker.process_one())
        clock.advance(600)  # au-delà du backoff maximal
    return outcomes


def test_a_long_outage_then_a_first_503_keeps_the_event_retryable(tmp_path):
    """Scénario de l'audit : 21 échecs de connexion puis un premier 503.
    Aujourd'hui : dead-letter immédiat. Attendu : encore réessayable, puis
    livré au 201 suivant, sans intervention."""
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("cut"))
    clock = Clock()
    sender = Script(
        *[TemporaryDeliveryError("connection refused")] * 21,
        HttpResult(503, "warming up"),
        ack("cut"),
    )
    worker = OutboxWorker(outbox, sender=sender, now=clock)

    outcomes = _drive(worker, clock, 23)

    assert outcomes[:21] == ["retry"] * 21
    assert outcomes[21] == "retry"  # le premier 503 n'est pas le vingtième
    assert outcomes[22] == "sent"
    assert read_dead_letter(database, "cut") is None
    assert outbox.counts() == (0, 0)


def test_repeated_503_alone_still_reach_the_limit_as_before(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("toxic"))
    clock = Clock()
    worker = OutboxWorker(outbox, sender=lambda _: HttpResult(503, "boom"), now=clock)

    outcomes = _drive(worker, clock, MAX_DELIVERY_ATTEMPTS)

    assert outcomes[:-1] == ["retry"] * (MAX_DELIVERY_ATTEMPTS - 1)
    assert outcomes[-1] == "dead-letter"
    assert read_dead_letter(database, "toxic")[2] == 503


def test_disconnections_alone_never_expire_and_never_count(tmp_path):
    """Contrôle : sans plafond, conformément à l'intention ; et le budget
    HTTP reste intact à zéro."""
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("offline"))
    clock = Clock()
    worker = OutboxWorker(
        outbox, sender=Script(*[TemporaryDeliveryError("no route")] * 40), now=clock
    )

    outcomes = _drive(worker, clock, 40)

    assert outcomes == ["retry"] * 40
    assert read_pending(database, "offline")[1] == 40  # backoff : attempts continue de compter
    assert read_http_attempts(database, "offline") == 0
    assert read_dead_letter(database, "offline") is None


def test_an_outage_across_a_worker_restart_still_does_not_count(tmp_path):
    """Le compteur est en SQLite, il survit au redémarrage : la coupure à
    cheval sur un redémarrage du worker ne doit pas non plus consommer le
    budget HTTP."""
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("restart"))
    clock = Clock()
    first = OutboxWorker(
        outbox, sender=Script(*[TemporaryDeliveryError("down")] * 15), now=clock
    )
    assert _drive(first, clock, 15) == ["retry"] * 15

    # Nouveau worker, nouvelle instance de l'outbox, même base.
    reopened = ProducerOutbox(database)
    second = OutboxWorker(
        reopened,
        sender=Script(*[TemporaryDeliveryError("down")] * 15, HttpResult(503, "x"), ack("restart")),
        now=clock,
    )
    outcomes = _drive(second, clock, 17)

    assert outcomes[:16] == ["retry"] * 16
    assert outcomes[16] == "sent"
    assert read_pending(database, "restart") is None
    assert read_dead_letter(database, "restart") is None


def test_a_database_created_without_the_column_is_migrated_and_delivered(tmp_path):
    """Base d'avant la colonne : migration additive et idempotente à
    l'ouverture, lignes existantes livrables, budget HTTP à zéro."""
    database = tmp_path / "outbox.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                next_attempt_at TEXT,
                last_error TEXT
            );
            CREATE TABLE dead_letters (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                error TEXT NOT NULL,
                http_status INTEGER,
                response_body TEXT,
                failed_at TEXT NOT NULL
            );
            CREATE TABLE producer_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        connection.execute(
            "INSERT INTO events(event_id, payload_json, created_at, attempts) VALUES (?, ?, ?, ?)",
            ("old", canonical_payload("old"), "2026-07-23T12:00:00+00:00", 7),
        )

    outbox = ProducerOutbox(database)
    ProducerOutbox(database)  # une seconde ouverture ne casse rien : idempotent
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
    assert "http_attempts" in columns
    assert read_http_attempts(database, "old") == 0
    assert read_pending(database, "old")[1] == 7  # attempts d'origine conservé

    clock = Clock()
    worker = OutboxWorker(outbox, sender=Script(HttpResult(503, "x"), ack("old")), now=clock)
    assert _drive(worker, clock, 1) == ["retry"]
    assert read_http_attempts(database, "old") == 1
    assert _drive(worker, clock, 1) == ["sent"]


def test_replay_dead_letter_starts_a_fresh_http_budget(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    outbox = ProducerOutbox(database)
    outbox.enqueue_payload(canonical_payload("again"))
    clock = Clock()
    worker = OutboxWorker(outbox, sender=lambda _: HttpResult(503, "boom"), now=clock)
    assert _drive(worker, clock, MAX_DELIVERY_ATTEMPTS)[-1] == "dead-letter"

    assert outbox.replay_dead_letters(event_id="again") == 1

    assert read_pending(database, "again")[1] == 0
    assert read_http_attempts(database, "again") == 0
