"""
Tests pour daemon/core/uid.py (UUIDv7)

Couvre :
  - Format UUID valide (32 hex + 4 tirets)
  - Version 7 dans le 3e groupe
  - Variant RFC 4122 dans le 4e groupe (8, 9, a ou b en tête)
  - Unicité sur N générations
  - Ordre chronologique (k-sortable)
  - Génération rapide sans blocage
"""

import re
import time
import unittest

from daemon.core.uid import new_uid

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class TestNewUid(unittest.TestCase):

    def test_format_uuid(self):
        uid = new_uid()
        self.assertRegex(uid, UUID_RE, f"Format invalide : {uid!r}")

    def test_version_7(self):
        for _ in range(20):
            uid = new_uid()
            version_nibble = uid.split("-")[2][0]
            self.assertEqual(version_nibble, "7", f"Version incorrecte dans : {uid}")

    def test_variant_rfc4122(self):
        """Le 4e groupe doit commencer par 8, 9, a ou b (variant 10xx)."""
        for _ in range(20):
            uid = new_uid()
            variant_nibble = uid.split("-")[3][0]
            self.assertIn(
                variant_nibble, "89ab",
                f"Variant RFC 4122 incorrect dans : {uid}"
            )

    def test_unicite(self):
        """1000 UIDs générés rapidement doivent tous être distincts."""
        uids = [new_uid() for _ in range(1000)]
        self.assertEqual(len(set(uids)), 1000, "Collision détectée dans 1000 UIDs")

    def test_ordre_chronologique(self):
        """
        Des UIDs générés séquentiellement doivent être triés dans l'ordre
        lexicographique (propriété k-sortable de UUIDv7).
        """
        uids = []
        for _ in range(50):
            uids.append(new_uid())
            time.sleep(0.001)  # 1ms entre chaque — assure un timestamp différent

        self.assertEqual(
            uids, sorted(uids),
            "Les UUIDv7 ne sont pas dans l'ordre lexicographique attendu"
        )

    def test_longueur_36_caracteres(self):
        uid = new_uid()
        self.assertEqual(len(uid), 36, f"Longueur incorrecte : {len(uid)}")

    def test_genere_rapidement(self):
        """10 000 UIDs doivent être générés en moins d'une seconde."""
        start = time.time()
        for _ in range(10_000):
            new_uid()
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0, f"Génération trop lente : {elapsed:.3f}s pour 10k UIDs")

    def test_timestamp_encode_dans_le_debut(self):
        """
        Les 48 premiers bits encodent le timestamp Unix en ms.
        Deux UIDs générés à plus de 1ms d'intervalle doivent avoir
        un préfixe différent.
        """
        uid1 = new_uid()
        time.sleep(0.01)  # 10ms
        uid2 = new_uid()
        prefix1 = uid1.replace("-", "")[:12]  # 48 bits = 12 hex
        prefix2 = uid2.replace("-", "")[:12]
        self.assertNotEqual(prefix1, prefix2,
                            "Les préfixes timestamp sont identiques après 10ms d'intervalle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
