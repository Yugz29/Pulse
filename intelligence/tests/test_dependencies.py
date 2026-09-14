"""L'extra mlx est épinglé : comparer des modèles suppose un runtime connu."""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

import pytest


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _mlx_pins() -> dict[str, str]:
    extra = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["mlx"]
    pins = {}
    for requirement in extra:
        name, separator, version = requirement.partition("==")
        assert separator and version.strip(), f"extra mlx non épinglé : {requirement!r}"
        pins[name.strip()] = version.strip()
    return pins


def test_the_mlx_extra_pins_mlx_lm_and_mlx_exactly():
    assert set(_mlx_pins()) == {"mlx-lm", "mlx"}


def test_the_installed_runtime_matches_the_pins():
    """Hors CI (où l'extra n'est pas installé) : la venv qui mesure les
    modèles tourne sur les versions déclarées, pas sur une mise à jour muette."""
    pins = _mlx_pins()
    try:
        installed = {name: metadata.version(name) for name in pins}
    except metadata.PackageNotFoundError:
        pytest.skip("extra mlx non installé")
    assert installed == pins
