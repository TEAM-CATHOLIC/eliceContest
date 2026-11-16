"""Configured local analyzer; ML packages are imported only on first inference."""

import os
from pathlib import Path


def is_configured() -> bool:
    """An explicit path opts into real inference, even when misconfigured.

    A bad configured path must raise rather than silently return fake results.
    """
    return bool(os.environ.get("ACCOUNT_CLEANER_MODEL_DIR", "").strip())


def create_analyzer():
    from .analyzer import LocalAccountAnalyzer

    value = os.environ.get("ACCOUNT_CLEANER_MODEL_DIR", "").strip()
    if not value:
        raise RuntimeError("ACCOUNT_CLEANER_MODEL_DIR에 로컬 AI 모델 폴더를 지정하세요.")
    directory = Path(value).expanduser().resolve()
    for name in ("manifest.json", "weights.json"):
        if not (directory / name).is_file():
            raise FileNotFoundError(f"로컬 AI 모델 파일이 없습니다: {name}")
    return LocalAccountAnalyzer(directory)
