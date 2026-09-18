"""Le prédicat de bruit de l'historique sans ``Path`` rend le verdict de
référence, chemins normalisés ou non.

``is_file_noise`` et ``attributed_workspace`` tournent une fois par
``file_changed`` de la journée (13 364 fois le 2026-09-17, 2,2 s de
``pathlib`` sur 2,8). Le chemin rapide sur chaînes ne s'engage que sur un
chemin que ``Path`` rendrait à l'identique ; ici, les deux voies sont
comparées à l'ancienne implémentation ``Path``, recopiée telle quelle, sur un
corpus qui mélange chemins propres, barres doublées, segments ``.`` et
``..``, barres finales, workspace racine, forme résolue du workspace et
racines de virtualenv.
"""
from itertools import product
from pathlib import Path

import pytest

from daemon_v2 import file_policy
from daemon_v2.file_policy import (
    attributed_workspace,
    is_file_noise,
    should_ignore,
    under_virtualenv,
    virtualenv_roots,
)


# --- Référence : l'implémentation d'avant, mot pour mot -----------------------


def _reference_attributed_workspace(path, workspace):
    if isinstance(workspace, dict):
        workspace = workspace.get("workspace_root")
    if workspace and not Path(path).is_relative_to(workspace):
        return None
    return workspace


def _reference_is_file_noise(path, workspace, virtualenvs):
    return bool(workspace and should_ignore(Path(path), Path(workspace))) or (
        under_virtualenv(Path(path), virtualenvs)
    )


# --- Corpus -------------------------------------------------------------------

WORKSPACES = [
    None,
    "",
    "/",
    "/Users/dev/Projets/Pulse",
    "/Users/dev/Projets/Pulse/",
    "/Users/dev//Projets/Pulse",
    "/Users/dev/Projets/./Pulse",
    "/Users/dev/Projets/Pulse-exp",
    {"workspace_root": "/Users/dev/Projets/Pulse"},
    {"workspace_root": None},
    {"other": "x"},
]

PATHS = [
    "/Users/dev/Projets/Pulse",
    "/Users/dev/Projets/Pulse/core/daemon_v2/routes.py",
    "/Users/dev/Projets/Pulse/.git/index",
    "/Users/dev/Projets/Pulse/.git",
    "/Users/dev/Projets/Pulse/core/.venv/lib/python3.14/site-packages/x.py",
    "/Users/dev/Projets/Pulse/DevNote-env/pyvenv.cfg",
    "/Users/dev/Projets/Pulse/DevNote-env/bin/python",
    "/Users/dev/Projets/Pulse/DevNote-env",
    "/Users/dev/Projets/Pulse/DevNote-environ/notes.md",
    "/Users/dev/Projets/Pulse/.DS_Store",
    "/Users/dev/Projets/Pulse/trace.db",
    "/Users/dev/Projets/Pulse/notes.tar.db",
    "/Users/dev/Projets/Pulse/a.",
    "/Users/dev/Projets/Pulse/.hidden",
    "/Users/dev/Projets/Pulse/core/__pycache__/x.pyc",
    "/Users/dev/Projets/Pulse/node_modules",
    "/Users/dev/Projets/Pulse/build/out.o",
    "/Users/dev/Projets/Pulse/src/build.rs",
    "/Users/dev/Projets/Pulse-exp/core/x.py",
    "/Users/dev/Projets/Pulse-exp",
    "/Users/dev/Projets/PulseX/x.py",
    "/Users/dev/Projets/Pulse//core/x.py",
    "/Users/dev/Projets/Pulse/core/./x.py",
    "/Users/dev/Projets/Pulse/core/../x.py",
    "/Users/dev/Projets/Pulse/core/",
    "/Users/dev/Projets/Pulse/.git/",
    "/",
    "/x.py",
    "/.git/x",
    "relative/path.py",
    "core/.git/x",
    "",
]

VIRTUALENV_SETS = [
    frozenset(),
    virtualenv_roots(["/Users/dev/Projets/Pulse/DevNote-env/pyvenv.cfg"]),
    virtualenv_roots(
        [
            "/Users/dev/Projets/Pulse/DevNote-env/pyvenv.cfg",
            "/Users/dev/Projets/Pulse-exp/core/.venv/pyvenv.cfg",
            "/tmp/venv/pyvenv.cfg",
        ]
    ),
    virtualenv_roots(["/pyvenv.cfg"]),
]


@pytest.mark.parametrize("workspace", WORKSPACES, ids=repr)
def test_attributed_workspace_matches_the_reference(workspace):
    for path in PATHS:
        assert attributed_workspace(path, workspace) == _reference_attributed_workspace(
            path, workspace
        ), (path, workspace)


@pytest.mark.parametrize("virtualenvs", VIRTUALENV_SETS, ids=lambda v: str(sorted(map(str, v))))
def test_is_file_noise_matches_the_reference(virtualenvs):
    for path, workspace in product(PATHS, WORKSPACES):
        root = _reference_attributed_workspace(path, workspace)
        assert is_file_noise(path, root, virtualenvs) == _reference_is_file_noise(
            path, root, virtualenvs
        ), (path, root, virtualenvs)


def test_the_fast_path_only_takes_paths_that_path_would_leave_untouched():
    # La garde d'entrée : un chemin accepté par le chemin rapide est un chemin
    # que ``Path`` rendrait à l'identique. L'inverse n'est pas exigé (``..``
    # est laissé à la référence).
    for candidate in PATHS + [w for w in WORKSPACES if isinstance(w, str)]:
        if file_policy._plain_absolute(candidate):
            assert str(Path(candidate)) == candidate, candidate
            assert candidate.startswith("/")
    assert not file_policy._plain_absolute("/a/../b")
    assert not file_policy._plain_absolute("/a/b/")
    assert not file_policy._plain_absolute("/a//b")
    assert not file_policy._plain_absolute("/a/./b")
    assert not file_policy._plain_absolute("a/b")
    assert not file_policy._plain_absolute("")
    assert file_policy._plain_absolute("/")
    assert file_policy._plain_absolute("/a/b.c")


def test_plain_name_suffix_follows_purepath():
    for name in ["x.py", "notes.tar.db", "a.", ".DS_Store", ".hidden", "noext", ".", "..", "a..b", "x.PY"]:
        assert file_policy._PlainName(name).suffix == Path(name).suffix, name
        assert file_policy._PlainName(name).name == name
