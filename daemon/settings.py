import json
from pathlib import Path
from typing import Any, Dict, Optional


SETTINGS_PATH = Path.home() / ".pulse" / "settings.json"


def load_runtime_settings(settings_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(settings_path) if settings_path else SETTINGS_PATH
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def save_runtime_settings(
    settings: Dict[str, Any],
    settings_path: Optional[Path] = None,
) -> None:
    path = Path(settings_path) if settings_path else SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
