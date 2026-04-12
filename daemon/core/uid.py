"""
uid.py — Génération d'identifiants uniques pour Pulse.

Utilise UUIDv7 (RFC 9562) :
  - 48 bits  : timestamp Unix en millisecondes  → tri chronologique natif
  - 4 bits   : version = 0111
  - 12 bits  : rand_a
  - 2 bits   : variant = 10
  - 62 bits  : rand_b

Propriétés :
  - K-sortable  : l'ordre lexicographique == l'ordre d'insertion
  - Sans dépendance externe (stdlib uniquement : os, time)
  - Compatible avec les colonnes TEXT PRIMARY KEY de SQLite
  - Distinguable d'un UUIDv4 par le chiffre de version (7xxx vs 4xxx)

Usage :
    from daemon.core.uid import new_uid
    entry_id = new_uid()   # "01968f3a-b2c1-7d4e-a3f2-0b1c2d3e4f56"
"""

import os
import time


def new_uid() -> str:
    """
    Génère un UUIDv7 time-ordered.

    Format : xxxxxxxx-xxxx-7xxx-[89ab]xxx-xxxxxxxxxxxx
    """
    ms   = int(time.time() * 1000)   # timestamp Unix en ms (48 bits utilisés)
    rand = os.urandom(10)             # 80 bits aléatoires

    b = bytearray(16)

    # ── Octets 0-5 : timestamp (48 bits) ─────────────────────────────────────
    b[0] = (ms >> 40) & 0xFF
    b[1] = (ms >> 32) & 0xFF
    b[2] = (ms >> 24) & 0xFF
    b[3] = (ms >> 16) & 0xFF
    b[4] = (ms >>  8) & 0xFF
    b[5] =  ms        & 0xFF

    # ── Octets 6-7 : version 7 (4 bits) + rand_a (12 bits) ───────────────────
    b[6] = 0x70 | (rand[0] & 0x0F)
    b[7] = rand[1]

    # ── Octets 8-15 : variant 10 (2 bits) + rand_b (62 bits) ─────────────────
    b[8] = 0x80 | (rand[2] & 0x3F)
    b[9:16] = rand[3:10]

    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
