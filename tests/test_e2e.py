#!/usr/bin/env python3
"""
test_e2e.py — Validation du flux MCP Python pur (sans Claude Desktop).

Usage :
    cd /path/to/Pulse
    python tests/test_e2e.py [COMMANDE]

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


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "rm -rf /tmp/test_pulse"
    tool_id = f"e2e-{int(time.time())}"

    print(f"\n{BOLD}=== Pulse E2E Test ==={RESET}")
    print(f"Daemon : {DAEMON_URL}")
    print(f"Command: {command!r}")
    print(f"ID     : {tool_id}\n")

    status, body = http_get("/ping")
    if status == 200:
        ok(f"Daemon actif : {body}")
    else:
        err(f"Daemon injoignable (status={status}). Lancez d'abord : python -m daemon.main")
        return 1

    poll_state = {"result": None}
    poll_event = threading.Event()
    auto_decision_sent = threading.Event()

    def poller():
        info("Poller démarré — poll /mcp/pending toutes les 500ms")
        for i in range(120):  # 60s max
            time.sleep(0.5)
            pending_status, pending_body = http_get("/mcp/pending")
            if pending_status == 204:
                print(f"  [{i*500}ms] /mcp/pending → 204 No Content (rien en attente)")
                continue
            if pending_status == 200 and pending_body:
                print(f"\n{GREEN}{BOLD}  [{i*500}ms] /mcp/pending → 200 ✓{RESET}")
                print("  JSON reçu :")
                for key, value in pending_body.items():
                    print(f"    {key}: {value!r}")
                poll_state["result"] = pending_body
                poll_event.set()

                time.sleep(0.3)
                print(f"\n  Envoi décision 'allow' pour tool_use_id={pending_body.get('tool_use_id')}")
                decision_status, decision_body = http_post("/mcp/decision", {
                    "tool_use_id": pending_body.get("tool_use_id"),
                    "decision": "allow"
                })
                if decision_status == 200:
                    ok(f"Décision envoyée → {decision_body}")
                else:
                    err(f"Erreur envoi décision : status={decision_status}")
                auto_decision_sent.set()
                return

            err(f"  Réponse inattendue : status={pending_status} body={pending_body}")

        err("Timeout : /mcp/pending n'a jamais retourné de commande en 60s")
        poll_event.set()

    poll_thread = threading.Thread(target=poller, daemon=True)
    poll_thread.start()

    print(f"\n{BOLD}Envoi POST /mcp/intercept (va bloquer jusqu'à la décision)...{RESET}")
    t0 = time.monotonic()
    intercept_status, result = http_post("/mcp/intercept", {
        "command": command,
        "tool_use_id": tool_id,
    })
    elapsed = time.monotonic() - t0

    print(f"\n{BOLD}=== Résultat /mcp/intercept ==={RESET}")
    print(f"  Durée     : {elapsed:.3f}s")
    print(f"  Status HTTP : {intercept_status}")

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
        err(f"Pas de résultat retourné (status={intercept_status})")

    print(f"\n{BOLD}=== Bilan ==={RESET}")

    poll_ok = poll_state["result"] is not None
    decision_ok = auto_decision_sent.is_set()
    timing_ok = 0.5 < elapsed < 55

    if poll_ok and decision_ok and timing_ok:
        ok("Flux Python pur OK — Si le panel Swift ne s'ouvre pas, le bug est dans l'app Swift.")
        info("Vérifier : PulseViewModel poll actif ? DaemonBridge.fetchPendingCommand() decode sans erreur ?")
        print()
        return 0

    if not poll_ok:
        err("Le poll /mcp/pending n'a jamais vu la commande → bug dans handlers.py ou /mcp/pending")
    elif not timing_ok:
        err("L'intercept n'a pas bloqué → bug dans intercept_command() ou threading Flask")

    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
