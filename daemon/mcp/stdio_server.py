import sys
import json
import time
import urllib.request
import urllib.error
from daemon.interpreter.command_interpreter import CommandInterpreter

interpreter = CommandInterpreter()
DAEMON_URL = "http://127.0.0.1:8765"


def _log(msg: str):
    """Log horodaté sur stderr (visible dans les logs Claude Desktop)."""
    ts = time.strftime("%H:%M:%S")
    print(f"[Pulse {ts}] {msg}", file=sys.stderr, flush=True)

TOOLS = [
    {
        "name": "analyze_command",
        "description": (
            "Analyse une commande shell avant exécution. "
            "Retourne une traduction en français et un niveau de risque. "
            "Utilise cet outil AVANT chaque commande bash."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command":     {"type": "string", "description": "La commande shell à analyser"},
                "tool_use_id": {"type": "string", "description": "Identifiant unique de cette commande"}
            },
            "required": ["command"]
        }
    }
]


def _post_daemon(path: str, body: dict, timeout: int = 65) -> dict | None:
    """POST vers le daemon principal. Retourne None si injoignable."""
    url = f"{DAEMON_URL}{path}"
    _log(f"POST {url} (timeout={timeout}s) body={json.dumps(body)[:120]}")
    t0 = time.monotonic()
    try:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw    = resp.read()
            result = json.loads(raw)
            elapsed = time.monotonic() - t0
            _log(f"POST {url} → {resp.status} en {elapsed:.3f}s | décision={result.get('decision')} allowed={result.get('allowed')}")
            return result
    except urllib.error.URLError as e:
        elapsed = time.monotonic() - t0
        _log(f"ERREUR URLError après {elapsed:.3f}s sur {url} : {e.reason}")
        _log("⚠ Daemon injoignable → fallback local (le daemon est-il démarré sur :8765 ?)")
        return None
    except Exception as e:
        elapsed = time.monotonic() - t0
        _log(f"ERREUR inattendue après {elapsed:.3f}s sur {url} : {type(e).__name__}: {e}")
        return None


def handle_request(request: dict) -> dict | None:
    method     = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pulse", "version": "0.1.0"}
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS}
        }

    elif method == "tools/call":
        params      = request.get("params", {})
        tool_name   = params.get("name")
        arguments   = params.get("arguments", {})

        if tool_name == "analyze_command":
            command     = arguments.get("command", "")
            tool_use_id = arguments.get("tool_use_id", f"cc-{id(command)}")

            _log(f"analyze_command : command={command!r} tool_use_id={tool_use_id}")

            # Essaie d'intercepter via le daemon (bloquant — attend la décision UI)
            result = _post_daemon("/mcp/intercept", {
                "command":     command,
                "tool_use_id": tool_use_id
            })

            if result is None:
                # Daemon injoignable → analyse locale sans bloquer
                _log("Fallback local — daemon injoignable")
                local = interpreter.interpret(command)
                result = {
                    "translated":  local.translated,
                    "risk_level":  local.risk_level,
                    "risk_score":  local.risk_score,
                    "is_read_only": local.is_read_only,
                    "warning":     local.warning,
                    "allowed":     True,   # pas de daemon = on laisse passer
                    "decision":    "allow"
                }

            risk_icons = {"safe":"✅","low":"🟡","medium":"🟠","high":"🔴","critical":"💀"}
            icon    = risk_icons.get(result.get("risk_level", ""), "❓")
            allowed = result.get("allowed", True)
            decision_text = "✅ Autorisé" if allowed else "❌ Refusé"

            text  = f"{icon} **{result.get('translated', command)}**\n\n"
            text += f"- Décision : {decision_text}\n"
            text += f"- Risque : {result.get('risk_level','?')} ({result.get('risk_score',0)}/100)\n"
            if result.get("warning"):
                text += f"- ⚠ {result['warning']}\n"

            if not allowed:
                text += "\n**La commande a été refusée par l'utilisateur. Ne pas l'exécuter.**"

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": text}]
                }
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
        }

    elif method and method.startswith("notifications/"):
        return None

    if request_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }
    return None


def main():
    _log("MCP stdio server démarré (PID={})".format(__import__("os").getpid()))
    _log(f"Daemon cible : {DAEMON_URL}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req  = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                print(json.dumps(resp), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }), flush=True)
        except Exception as e:
            print(f"[Pulse] Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
