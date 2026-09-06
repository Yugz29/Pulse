"""CLI enfant synchronisée à une frontière précise, sans course par sleep."""

from contextlib import contextmanager
import os
from pathlib import Path
import selectors
import subprocess
import sys


INTELLIGENCE_DIR = Path(__file__).resolve().parents[1]
CHILD = """
import sys
from pulse_intelligence import cli
from pulse_intelligence.core_client import CoreClient

def pause():
    print('PULSE_TEST_PAUSED', flush=True)
    if sys.stdin.readline() != 'continue\\n':
        raise RuntimeError('test controller disconnected')

stage = sys.argv.pop(1)
if stage == 'before_generation':
    original = cli._summarizer
    def blocked(*args, **kwargs):
        pause()
        return original(*args, **kwargs)
    cli._summarizer = blocked
elif stage == 'after_acceptance':
    original = CoreClient.post_activity
    def blocked(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.accepted:
            pause()
        return result
    CoreClient.post_activity = blocked
else:
    raise ValueError(stage)
sys.exit(cli.main(sys.argv[1:]))
"""


def cli_environment(tmp_path):
    home = tmp_path / "cli-home"
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(
        'model_id = "fake/summarizer"\nprompt_version = "v1"\n', encoding="utf-8"
    )
    return {**os.environ, "HOME": str(home), "PULSE_INTELLIGENCE_HOME": str(home),
            "PYTHONDONTWRITEBYTECODE": "1"}


def run_cli(args, env):
    return subprocess.run(
        [sys.executable, "-m", "pulse_intelligence.cli", *args],
        cwd=INTELLIGENCE_DIR, env=env, capture_output=True, text=True, timeout=15,
    )


@contextmanager
def paused_cli(args, env, *, stage):
    process = subprocess.Popen(
        [sys.executable, "-c", CHILD, stage, *args], cwd=INTELLIGENCE_DIR,
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=15), "CLI did not reach the requested boundary"
        marker = process.stdout.readline()
        assert marker == "PULSE_TEST_PAUSED\n", (marker, process.poll())
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
