import json
import threading
from flask import Flask, Response, request, jsonify
from daemon.mcp.handlers import intercept_command, receive_decision, get_pending_count

mcp_app = Flask(__name__)


@mcp_app.route("/mcp")
def mcp_sse():
    """
    Point d'entrée SSE pour Claude Code.
    Claude Code se connecte ici et reste en écoute.
    """
    def stream():
        # Annonce les capabilities au client MCP
        yield _sse({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pulse", "version": "0.1.0"}
            }
        })

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@mcp_app.route("/mcp/command", methods=["POST"])
def mcp_command():
    """
    Reçoit une commande bash de Claude Code.
    Bloque jusqu'à ce que l'utilisateur décide (allow/deny).
    """
    data = request.get_json()
    command = data.get("command", "")
    tool_use_id = data.get("tool_use_id", "unknown")

    # Analyse + attend la décision dans un thread bloquant
    result = intercept_command(command, tool_use_id)

    return jsonify(result)


@mcp_app.route("/mcp/decision", methods=["POST"])
def mcp_decision():
    """
    Reçoit la décision (allow/deny) depuis Swift ou le terminal.
    """
    data = request.get_json()
    tool_use_id = data.get("tool_use_id")
    decision = data.get("decision")  # "allow" ou "deny"

    ok = receive_decision(tool_use_id, decision)
    return jsonify({"ok": ok})


@mcp_app.route("/mcp/status")
def mcp_status():
    """Retourne le nombre de commandes en attente."""
    return jsonify({"pending": get_pending_count()})


def _sse(data: dict) -> str:
    """Formate un event SSE."""
    return f"data: {json.dumps(data)}\n\n"


def start_mcp_server(host: str = "127.0.0.1", port: int = 8766):
    """Lance le serveur MCP dans un thread séparé."""
    thread = threading.Thread(
        target=lambda: mcp_app.run(host=host, port=port, debug=False),
        daemon=True
    )
    thread.start()
    print(f"✓ MCP server démarré sur http://{host}:{port}")
