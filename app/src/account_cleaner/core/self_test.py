"""빌드한 실행파일이 제대로 묶였는지 확인한다 (`account-cleaner --self-test`).

CI에서 PyInstaller 결과물을 실제로 실행해 Qt, 리소스 파일, Playwright 드라이버, Chrome 실행까지
확인한다. 창은 띄우지 않는다.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        return f"{'OK  ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


def check_qt() -> Check:
    from PySide6.QtWidgets import QApplication

    from account_cleaner.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.close()
    window.deleteLater()
    return Check("qt", True, f"platform={app.platformName()}")


def check_resources() -> Check:
    """패키지에 들어 있어야 할 데이터 파일(예시 플레이북 등)."""
    try:
        from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR
    except ImportError:
        return Check("resources", True, "예시 플레이북 없음 (건너뜀)")

    files = sorted(Path(str(SAMPLE_PLAYBOOK_DIR)).glob("*.json"))
    return Check("resources", bool(files), f"예시 플레이북 {len(files)}개")


def check_gmail() -> Check:
    """Gmail API 클라이언트를 네트워크 없이 만들 수 있는지 (디스커버리 문서·인증서 포함 여부)."""
    import httplib2.certs
    from google.auth.credentials import AnonymousCredentials

    from account_cleaner.mail.gmail import GoogleGmailApi

    GoogleGmailApi(AnonymousCredentials())
    certs = Path(httplib2.certs.where())
    return Check("gmail", certs.is_file(), f"discovery gmail.v1, certs={certs.name}")


def check_providers() -> Check:
    """providers가 문자열 이름으로 불러오는 실제 구현 모듈이 빌드에 들어 있는지 (#76)."""
    import importlib

    from account_cleaner.providers import _REAL

    modules = sorted({module for module, _attr in _REAL.values()})
    for module in modules:
        importlib.import_module(module)
    return Check("providers", True, ", ".join(modules))


def check_llm() -> Check:
    """범용 안내(#73)에 쓰는 Anthropic SDK와 pydantic이 빌드에 들어 있는지. 네트워크는 쓰지 않는다."""
    import anthropic
    import pydantic

    from account_cleaner.browser.agent.llm import AnthropicNextClickSelector

    AnthropicNextClickSelector("self-test")._get_client()
    return Check("llm", True, f"anthropic {anthropic.__version__}, pydantic {pydantic.VERSION}")


def check_keychain() -> Check:
    """근거 메일 암호화 키를 둘 OS 키체인 백엔드가 묶였는지 (키를 쓰거나 읽지는 않는다).

    macOS·Windows 배포본은 키체인이 꼭 있어야 하고, 리눅스는 없으면 키 파일로 대신한다.
    """
    import sys

    from account_cleaner.storage.crypto import KeyringKeyStore, KeyStoreUnavailable

    try:
        backend = KeyringKeyStore()._backend()
    except KeyStoreUnavailable as e:
        return Check("keychain", not sys.platform.startswith(("darwin", "win")), str(e))
    return Check("keychain", True, type(backend).__module__)


def check_browser(require_chrome: bool) -> list[Check]:
    from playwright._impl._driver import compute_driver_executable
    from playwright.sync_api import sync_playwright

    from account_cleaner.core.chrome import find_chrome

    node, cli = compute_driver_executable()
    driver_ok = Path(node).is_file() and Path(cli).is_file()
    checks = [Check("playwright driver", driver_ok, str(Path(node).parent))]
    if not driver_ok:
        return checks

    chrome = find_chrome()
    if chrome is None:
        checks.append(Check("chrome", not require_chrome, "설치된 Chrome 없음"))
        return checks

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.set_content("<title>self-test</title>")
            title = page.title()
        finally:
            browser.close()
    checks.append(Check("chrome", title == "self-test", f"{chrome} (version {browser.version})"))
    return checks


def run_self_test(require_chrome: bool = False) -> list[Check]:
    checks: list[Check] = []
    for name, fn in (
        ("qt", check_qt),
        ("resources", check_resources),
        ("gmail", check_gmail),
        ("providers", check_providers),
        ("llm", check_llm),
        ("keychain", check_keychain),
    ):
        try:
            checks.append(fn())
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 결과로 보고한다
            checks.append(Check(name, False, repr(e)))
    try:
        checks.extend(check_browser(require_chrome))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("browser", False, repr(e)))
    return checks
