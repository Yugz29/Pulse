"""
Tests de migration du schéma legacy MemoryStore.

Couvre le cas P1 identifié en audit : une DB existante avec
id INTEGER AUTOINCREMENT (ancien schéma) doit être migrée
automatiquement vers id TEXT (UUIDv7) sans perte de données.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from daemon.memory.store import MemoryStore


def _create_legacy_db(path: Path) -> None:
    """
    Crée une DB avec l'ancien schéma INTEGER AUTOINCREMENT
    et insère quelques lignes pour vérifier la migration.
    """
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE memory_entries (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tier             TEXT NOT NULL,
            topic            TEXT NOT NULL DEFAULT 'general',
            content          TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            last_accessed_at TEXT,
            expires_at       TEXT,
            source           TEXT DEFAULT 'daemon'
        )
    """)
    now = "2026-01-01T10:00:00"
    conn.execute(
        "INSERT INTO memory_entries (tier, topic, content, created_at, updated_at, source)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("persistent", "fact", "Contenu legacy A", now, now, "daemon"),
    )
    conn.execute(
        "INSERT INTO memory_entries (tier, topic, content, created_at, updated_at, source)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("session", "general", "Contenu legacy B", now, now, "llm"),
    )
    conn.commit()
    conn.close()


class TestMemoryStoreMigration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "memory.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_detecte_schema_legacy(self):
        """MemoryStore s'ouvre sans erreur sur une DB legacy."""
        _create_legacy_db(self.db_path)
        # Ne doit pas lever d'exception
        store = MemoryStore(db_path=self.db_path)
        self.assertIsNotNone(store)

    def test_migration_preserve_le_contenu(self):
        """Les entrées legacy sont présentes après migration."""
        _create_legacy_db(self.db_path)
        store = MemoryStore(db_path=self.db_path)
        entries = store.list_entries()
        contents = [e["content"] for e in entries]
        self.assertIn("Contenu legacy A", contents)
        self.assertIn("Contenu legacy B", contents)

    def test_migration_convertit_ids_en_uuid(self):
        """Les IDs sont des UUIDv7 (TEXT) après migration, pas des entiers."""
        _create_legacy_db(self.db_path)
        store = MemoryStore(db_path=self.db_path)
        entries = store.list_entries()
        for e in entries:
            parts = e["id"].split("-")
            self.assertEqual(len(parts), 5, f"ID non-UUID : {e['id']}")
            self.assertTrue(parts[2].startswith("7"),
                            f"Version UUID incorrecte : {e['id']}")

    def test_migration_preserves_tier_et_source(self):
        """Les métadonnées sont correctement copiées."""
        _create_legacy_db(self.db_path)
        store = MemoryStore(db_path=self.db_path)
        entries = {e["content"]: e for e in store.list_entries()}
        self.assertEqual(entries["Contenu legacy A"]["tier"], "persistent")
        self.assertEqual(entries["Contenu legacy A"]["source"], "daemon")
        self.assertEqual(entries["Contenu legacy B"]["tier"], "session")
        self.assertEqual(entries["Contenu legacy B"]["source"], "llm")

    def test_write_fonctionne_apres_migration(self):
        """On peut écrire après migration sans erreur de type."""
        _create_legacy_db(self.db_path)
        store = MemoryStore(db_path=self.db_path)
        result = store.write("Nouvelle entrée post-migration", tier="session")
        self.assertTrue(result["ok"])
        entries = store.list_entries()
        contents = [e["content"] for e in entries]
        self.assertIn("Nouvelle entrée post-migration", contents)

    def test_migration_idempotente(self):
        """Ouvrir deux fois la même DB ne duplique pas les entrées."""
        _create_legacy_db(self.db_path)
        MemoryStore(db_path=self.db_path)   # première ouverture → migration
        store2 = MemoryStore(db_path=self.db_path)  # deuxième → no-op
        entries = store2.list_entries()
        # Les 2 entrées legacy, pas 4
        self.assertEqual(len(entries), 2)

    def test_schema_neuf_non_migre(self):
        """Une DB neuve (schéma TEXT) n'est pas touchée par la migration."""
        store = MemoryStore(db_path=self.db_path)
        store.write("Entrée neuve", tier="session")
        # Deuxième ouverture : aucune migration ne doit se déclencher
        store2 = MemoryStore(db_path=self.db_path)
        entries = store2.list_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["content"], "Entrée neuve")


if __name__ == "__main__":
    unittest.main()
