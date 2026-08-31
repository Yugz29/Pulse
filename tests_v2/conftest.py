import pytest


@pytest.fixture(autouse=True)
def _isolated_agent_sessions_manifest(tmp_path, monkeypatch):
    """Aucun test ne lit le manifeste réel de la machine.

    /status compte désormais les sessions regrossies depuis le manifeste
    producteur : sans cette isolation, chaque test de route stat-erait les
    vrais transcripts de ~/.claude et ~/.codex.
    """
    monkeypatch.setenv(
        "PULSE_AGENT_SESSIONS_MANIFEST_PATH",
        str(tmp_path / "agent_sessions_manifest.json"),
    )
