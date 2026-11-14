"""설치된 Google Chrome 찾기.

브라우저 에이전트는 Playwright로 설치된 Chrome(`channel="chrome"`)을 조종한다. PoC는 Chrome
설치를 전제로 하므로 (PRD 5장), 없으면 앱 시작 시 안내한다.
"""

import os
import shutil
import sys
from pathlib import Path

CHROME_DOWNLOAD_URL = "https://www.google.com/chrome/"


def chrome_candidates() -> list[Path]:
    """OS별로 Chrome이 흔히 설치되는 위치."""
    if sys.platform == "win32":
        bases = (os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"))
        return [Path(b) / "Google/Chrome/Application/chrome.exe" for b in bases if b]
    if sys.platform == "darwin":
        rel = "Google Chrome.app/Contents/MacOS/Google Chrome"
        return [Path("/Applications") / rel, Path.home() / "Applications" / rel]
    found = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable")]
    return [Path(p) for p in found if p] + [Path("/opt/google/chrome/chrome")]


def find_chrome() -> Path | None:
    return next((p for p in chrome_candidates() if p.is_file()), None)
