"""Flask application factory and local daemon entry point."""

from pathlib import Path

from flask import Flask

from .routes import api
from .runtime_config import (
    core_base_url,
    core_host,
    core_port,
    reconstruction_timezone,
    select_database_path,
)
from .private_files import apply_private_umask
from .trace_store import TraceStore


def create_app(database_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    # Échec explicite au démarrage si PULSE_RECONSTRUCTION_TZ est invalide.
    reconstruction_timezone()
    path = select_database_path(database_path)
    app.config["DATABASE_PATH"] = path
    app.config["TRACE_STORE"] = TraceStore(path)
    app.config["CORE_BASE_URL"] = core_base_url()
    app.register_blueprint(api)
    return app


def main() -> None:
    apply_private_umask()
    app = create_app()
    print(f"Pulse V2 database: {app.config['DATABASE_PATH']}", flush=True)
    app.run(host=core_host(), port=core_port(), debug=False)


if __name__ == "__main__":
    main()
