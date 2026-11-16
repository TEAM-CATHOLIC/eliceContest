import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from account_cleaner.contracts import AccountCandidate
from account_cleaner.core.chrome import CHROME_DOWNLOAD_URL, find_chrome
from account_cleaner.core.log_setup import setup_logging
from account_cleaner.core.paths import resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.agent_page import AgentPage
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage
from account_cleaner.ui.errors import install_excepthook, show_exception
from account_cleaner.ui.main_window import APP_TITLE, MainWindow, PageId
from account_cleaner.ui.workers import BackgroundTask

ORGANIZATION = "TEAM-CATHOLIC"
APPLICATION = "AccountCleaner"

log = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="account-cleaner")
    parser.add_argument(
        "--self-test", action="store_true", help="창 없이 묶인 구성요소를 확인하고 종료"
    )
    parser.add_argument("--require-chrome", action="store_true", help="Chrome이 없으면 실패")
    parser.add_argument("--report", type=Path, help="self-test 결과를 쓸 파일")
    # macOS가 붙이는 -psn_* 같은 인자와 Qt 인자는 무시한다.
    args, _ = parser.parse_known_args(argv)
    return args


def self_test(args: argparse.Namespace) -> int:
    from account_cleaner.core.self_test import run_self_test

    checks = run_self_test(require_chrome=args.require_chrome)
    text = "\n".join(c.line() for c in checks) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    if sys.stdout is not None:  # 창 모드 실행파일(Windows)에는 stdout이 없다
        sys.stdout.write(text)
    return 0 if all(c.ok for c in checks) else 1


def warn_if_chrome_missing(parent: QWidget) -> None:
    if find_chrome() is not None:
        return
    log.warning("Chrome을 찾지 못함")
    QMessageBox.warning(
        parent,
        "Chrome이 필요합니다",
        "탈퇴 화면 안내는 Google Chrome으로 진행합니다.\n"
        f"Chrome을 설치한 뒤 앱을 다시 실행해 주세요.\n\n{CHROME_DOWNLOAD_URL}",
    )


def start_agent_for(
    window: MainWindow, inventory: InventoryPage, agent_page: AgentPage, candidate: AccountCandidate
) -> None:
    """후보 상세의 'AI 에이전트로 탈퇴 진행' → 에이전트 화면으로 가서 그 서비스 안내 시작."""
    playbook = agent_page.playbook_for_domain(candidate.domain)
    if playbook is None:
        return
    window.show_page(PageId.AGENT)
    if agent_page.start_for(playbook.id):
        inventory.set_status(candidate.domain, CandidateStatus.IN_PROGRESS)


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.self_test:
        return self_test(args)

    app = QApplication(sys.argv)
    app.setOrganizationName(ORGANIZATION)
    app.setApplicationName(APPLICATION)
    app.setApplicationDisplayName(APP_TITLE)

    try:
        paths = resolve_app_paths()
    except (OSError, RuntimeError) as e:
        show_exception(None, e, "앱 데이터 폴더를 만들 수 없습니다.")
        return 1

    setup_logging(paths.logs)
    install_excepthook()
    log.info("앱 시작 (데이터 폴더: %s)", paths.root)

    window = MainWindow(AppSettings(paths.settings_file))
    agent_page = AgentPage(paths.browser_profile)
    inventory = InventoryPage()
    inventory.detail.set_playbook_lookup(agent_page.playbook_for_domain)
    window.top_bar.search_changed.connect(inventory.set_search)
    inventory.agent_requested.connect(
        lambda candidate: start_agent_for(window, inventory, agent_page, candidate)
    )
    window.set_page(PageId.INVENTORY, inventory)
    window.set_page(PageId.AGENT, agent_page)
    app.aboutToQuit.connect(BackgroundTask.shutdown_all)
    window.show()
    QTimer.singleShot(0, lambda: warn_if_chrome_missing(window))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
