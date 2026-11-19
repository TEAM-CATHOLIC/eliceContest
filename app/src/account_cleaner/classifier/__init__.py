"""Configured local analyzer; ML packages are imported only on first inference."""

import os
from importlib import resources
from pathlib import Path

BUNDLED_MODEL_DIR = Path(str(resources.files(__package__) / "bundled"))
"""Model folder shipped inside a build that includes the AI model. Not in the repository."""


def _model_dir() -> Path | None:
    """The explicit path wins; otherwise a model bundled with the app, if any."""
    value = os.environ.get("ACCOUNT_CLEANER_MODEL_DIR", "").strip()
    if value:
        return Path(value).expanduser().resolve()
    if (BUNDLED_MODEL_DIR / "manifest.json").is_file():
        return BUNDLED_MODEL_DIR
    return None


def is_configured() -> bool:
    """An explicit path opts into real inference, even when misconfigured.

    A bad configured path must raise rather than silently return fake results.
    """
    return _model_dir() is not None


def create_analyzer():
    from .analyzer import LocalAccountAnalyzer

    directory = _model_dir()
    if directory is None:
        raise RuntimeError("ACCOUNT_CLEANER_MODEL_DIR에 로컬 AI 모델 폴더를 지정하세요.")
    for name in ("manifest.json", "weights.json"):
        if not (directory / name).is_file():
            raise FileNotFoundError(f"로컬 AI 모델 파일이 없습니다: {name}")
    return LocalAccountAnalyzer(directory)
