#!/usr/bin/env python3
"""
test_e2e.py — Validation du flux MCP Python pur (sans Claude Desktop).

Usage :
    cd /Users/yugz/Projets/Pulse/Pulse
    python test_e2e.py [COMMANDE]

Ce script :
  1. Vérifie que le daemon répond sur :8765
  2. Lance un thread qui poll /mcp/pending toutes les 500ms
  3. Envoie POST /mcp/intercept (bloquant) en simulant stdio_server.py
  4. Dès que le poll détecte la commande, affiche le JSON retourné
  5. Envoie automatiquement une décision "allow" pour débloquer l'intercept
  6. Affiche le résultat final retourné par /mcp/intercept

Interprétation des résultats :
  - Si le poll détecte la commande → le flux Python fonctionne correctement.
    Vérifier ensuite du côté Swift (PulseViewModel / DaemonBridge).
  - Si /mcp/intercept retourne immédiatement → bug dans handlers.py ou Flask.
  - Si connexion refusée → le daemon n'est pas démarré.
"""

import sys
import json
import time
import threading
import urllib.request
import urllib.error

DAEMON_URL = "http://127.0.0.1:8765"
COMMAND    = sys.argv[1] if len(sys.argv) > 1 else "rm -rf /tmp/test_pulse"
TOOL_ID    = f"e2e-{int(time.time())}"

# ─── Couleurs terminal ─────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):    print(f"{GREEN}✓ {msg}{RESET}")
def warn(msg):  print(f"{YELLOW}⚠ {msg}{RESET}")
def err(msg):   print(f"{RED}✗ {msg}{RESET}")
def info(msg):  print(f"{CYAN}  {msg}{RESET}")


# ─── Helpers HTTP ──────────────────────────────────────────────────────────────

def http_get(path: str, timeout: int = 5) -> tuple[int, dict | None]:
    try:
        with urllib.request.urlopen(f"{DAEMON_URL}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read()) if r.length != 0 else None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, None


def http_post(path: str, body: dict, timeout: int = 70) -> tuple[int, dict | None]:
    try:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            f"{DAEMON_URL}{path}", data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, None


# ─── 1. Ping ───────────────────────────────────────────────────────────────────

print(f"\n{BOLD}=== Pulse E2E Test ==={RESET}")
print(f"Daemon : {DAEMON_URL}")
print(f"Command: {COMMAND!r}")
print(f"ID     : {TOOL_ID}\n")

status, body = http_get("/ping")
if status == 200:
    ok(f"Daemon actif : {body}")
else:
    err(f"Daemon injoignable (status={status}). Lancez d'abord : python -m daemon.main")
    sys.exit(1)


# ─── 2. Thread poll /mcp/pending ──────────────────────────────────────────────

poll_result: dict | None  = None
poll_event                = threading.Event()
auto_decision_sent        = threading.Event()

def poller():
    global poll_result
    info("Poller démarré — poll /mcp/pending toutes les 500ms")
    for i in range(120):  # 60s max
        time.sleep(0.5)
        status, body = http_get("/mcp/pending")
        if status == 204:
            print(f"  [{i*500}ms] /mcp/pending → 204 No Content (rien en attente)")
            continue
        if status == 200 and body:
            print(f"\n{GREEN}{BOLD}  [{i*500}ms] /mcp/pending → 200 ✓{RESET}")
            print(f"  JSON reçu :")
            for k, v in body.items():
                print(f"    {k}: {v!r}")
            poll_result = body
            poll_event.set()

            # Envoie automatiquement "allow" pour débloquer l'intercept
            time.sleep(0.3)
            print(f"\n  Envoi décision 'allow' pour tool_use_id={body.get('tool_use_id')}")
            s2, b2 = http_post("/mcp/decision", {
                "tool_use_id": body.get("tool_use_id"),
                "decision":    "allow"
            })
            if s2 == 200:
                ok(f"Décision envoyée → {b2}")
            else:
                err(f"Erreur envoi décision : status={s2}")
            auto_decision_sent.set()
            return
        else:
            err(f"  Réponse inattendue : status={status} body={body}")
    err("Timeout : /mcp/pending n'a jamais retourné de commande en 60s")
    poll_event.set()

poll_thread = threading.Thread(target=poller, daemon=True)
poll_thread.start()


# ─── 3. POST /mcp/intercept (bloquant) ────────────────────────────────────────

print(f"\n{BOLD}Envoi POST /mcp/intercept (va bloquer jusqu'à la décision)...{RESET}")
t0 = time.monotonic()

status, result = http_post("/mcp/intercept", {
    "command":     COMMAND,
    "tool_use_id": TOOL_ID,
})

elapsed = time.monotonic() - t0


# ─── 4. Résultats ─────────────────────────────────────────────────────────────

print(f"\n{BOLD}=== Résultat /mcp/intercept ==={RESET}")
print(f"  Durée     : {elapsed:.3f}s")
print(f"  Status HTTP : {status}")

if elapsed < 0.5:
    err(f"SUSPECT : réponse en {elapsed:.3f}s — /mcp/intercept n'a pas bloqué !")
    warn("Vérifier que handlers.intercept_command() appelle bien decision_queue.get(timeout=60)")
elif elapsed > 55:
    warn(f"Timeout déclenché côté handlers ({elapsed:.1f}s)")
else:
    ok(f"Bloqué correctement pendant {elapsed:.2f}s")

if result:
    print(f"\n  Décision  : {result.get('decision')}")
    print(f"  Allowed   : {result.get('allowed')}")
    print(f"  Risk      : {result.get('risk_level')} ({result.get('risk_score')}/100)")
    print(f"  Traduit   : {result.get('translated')}")
    if result.get("warning"):
        warn(f"  Warning   : {result['warning']}")
else:
    err(f"Pas de résultat retourné (status={status})")


# ─── 5. Bilan ─────────────────────────────────────────────────────────────────

print(f"\n{BOLD}=== Bilan ==={RESET}")

poll_ok    = poll_result is not None
decision_ok = auto_decision_sent.is_set()
timing_ok  = 0.5 < elapsed < 55

if poll_ok and decision_ok and timing_ok:
    ok("Flux Python pur OK — Si le panel Swift ne s'ouvre pas, le bug est dans l'app Swift.")
    info("Vérifier : PulseViewModel poll actif ? DaemonBridge.fetchPendingCommand() decode sans erreur ?")
elif not poll_ok:
    err("Le poll /mcp/pending n'a jamais vu la commande → bug dans handlers.py ou /mcp/pending")
elif not timing_ok:
    err("L'intercept n'a pas bloqué → bug dans intercept_command() ou threading Flask")

print()
