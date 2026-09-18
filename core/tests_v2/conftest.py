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


@pytest.fixture(autouse=True)
def _isolated_agent_state_dir(tmp_path, monkeypatch):
    """Aucun test ne lit le dossier d'état des agents du poste
    (``~/.pulse_v2/run/agents``) : la page rendue par un test montrerait la
    session Claude Code qui fait tourner la suite. Chaque test part d'un
    dossier vide et y pose ce dont il a besoin."""
    monkeypatch.setenv("PULSE_AGENT_STATE_DIR", str(tmp_path / "agents-empty"))
