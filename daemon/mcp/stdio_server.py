import sys
import json
from daemon.interpreter.command_interpreter import CommandInterpreter

interpreter = CommandInterpreter()

# L'outil exposé à Claude Desktop
TOOLS = [
    {
        "name": "analyze_command",
        "description": (
            "Analyse une commande shell avant exécution. "
            "Retourne une traduction en français et un niveau de risque (safe/low/medium/high/critical)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "La commande shell à analyser"
                }
            },
            "required": ["command"]
        }
    }
]


def handle_request(request: dict) -> dict | None:
    """Traite un message JSON-RPC entrant et retourne la réponse."""
    method     = request.get("method")
    request_id = request.get("id")

    # Handshake initial — Claude Desktop annonce ses capabilities
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

    # Liste des outils disponibles
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS}
        }

    # Appel d'un outil
    elif method == "tools/call":
        params    = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "analyze_command":
            command = arguments.get("command", "")
            result  = interpreter.interpret(command)

            # Formate la réponse lisible pour Claude Desktop
            risk_icons = {
                "safe":     "✅",
                "low":      "🟡",
                "medium":   "🟠",
                "high":     "🔴",
                "critical": "💀",
            }
            icon = risk_icons.get(result.risk_level, "❓")

            text  = f"{icon} **{result.translated}**\n\n"
            text += f"- Risque : {result.risk_level} ({result.risk_score}/100)\n"
            text += f"- Lecture seule : {'oui' if result.is_read_only else 'non'}\n"
            text += f"- Affecte : {', '.join(result.affects)}\n"
            if result.warning:
                text += f"- ⚠ {result.warning}\n"
            if result.needs_llm:
                text += "- ℹ Commande inconnue — analyse basique\n"

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": text}]
                }
            }

        # Outil inconnu
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
        }

    # Notifications — pas de réponse attendue
    elif method and method.startswith("notifications/"):
        return None

    # Méthode inconnue
    if request_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }
    return None


def main():
    print("[Pulse] MCP stdio server started", file=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request  = json.loads(line)
            response = handle_request(request)

            if response is not None:
                # flush=True — critique : Claude Desktop attend la réponse immédiatement
                print(json.dumps(response), flush=True)

        except json.JSONDecodeError as e:
            print(json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }), flush=True)

        except Exception as e:
            print(f"[Pulse] Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
