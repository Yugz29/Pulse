from flask import Flask, request, jsonify
from daemon.interpreter.command_interpreter import CommandInterpreter

app = Flask(__name__)
interpreter = CommandInterpreter()


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "version": "0.1.0"})


@app.route("/mcp/intercept", methods=["POST"])
def mcp_intercept():
    data = request.get_json()
    command = data.get("command", "")
    tool_use_id = data.get("tool_use_id", "unknown")

    result = interpreter.interpret(command)

    return jsonify({
        "tool_use_id":  tool_use_id,
        "command":      result.original,
        "translated":   result.translated,
        "risk_level":   result.risk_level,
        "risk_score":   result.risk_score,
        "is_read_only": result.is_read_only,
        "affects":      result.affects,
        "warning":      result.warning,
        "needs_llm":    result.needs_llm,
    })


if __name__ == "__main__":
    print("✓ Pulse daemon démarré sur http://localhost:8765")
    app.run(host="127.0.0.1", port=8765, debug=False)
