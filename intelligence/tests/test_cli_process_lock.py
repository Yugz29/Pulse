"""Le verrou protège l'état entre de vrais processus, y compris après SIGKILL."""

import pytest

from cli_process_support import cli_environment, paused_cli, run_cli
from conftest import REFERENCE, session_view
from pulse_intelligence.session_summary import summary_event_id
from pulse_intelligence.state import JobState


@pytest.mark.parametrize("kill_owner", [False, True], ids=["normal-exit", "sigkill"])
def test_process_lock_preserves_state_and_is_released(
    fake_core, tmp_path, fake_output_file, kill_owner
):
    session_id = "aaaaaaaaaaaaaaaa"
    date = REFERENCE.date().isoformat()
    fake_core.add_sessions(date, session_view(session_id))
    path = tmp_path / "state.json"
    state = JobState.load(path)
    state.record_emitted(
        "existing", session_id="bbbbbbbbbbbbbbbb", prompt_version="v1",
        model_id="fake/summarizer", at=REFERENCE.isoformat(),
    )
    before = path.read_bytes()
    env = cli_environment(tmp_path)
    base = ["--core-url", fake_core.url, "--state", str(path)]
    args = [*base, "summarize", session_id, "--date", date,
            "--fake", str(fake_output_file)]

    with paused_cli(args, env, stage="before_generation") as owner:
        contender = run_cli(args, env)
        assert contender.returncode == 5, (contender.stdout, contender.stderr)
        assert "verrou" in contender.stderr
        assert path.read_bytes() == before
        assert fake_core.posts == []
        # La lecture reste disponible pendant que le producteur tient flock.
        reader = run_cli([*base, "list", "--date", date], env)
        assert reader.returncode == 0, reader.stderr
        assert session_id in reader.stdout
        assert path.read_bytes() == before
        if kill_owner:
            owner.kill()
            owner.communicate(timeout=5)
            assert owner.returncode < 0
        else:
            stdout, stderr = owner.communicate("continue\n", timeout=15)
            assert owner.returncode == 0, (stdout, stderr)

    # Un nouveau processus récupère le verrou, sans écraser l'entrée ancienne.
    restarted = run_cli(args, env)
    assert restarted.returncode == 0, (restarted.stdout, restarted.stderr)
    event_id = summary_event_id(session_id, "v1", "fake/summarizer")
    confirmed = JobState.load(path)
    assert set(confirmed.emitted) == {"existing", event_id}
    assert confirmed.pending == {}
    assert len(fake_core.posts) == 1
