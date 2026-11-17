import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from account_cleaner.contracts import AccountCandidate, AgentEvent, AgentStatus
from account_cleaner.core.chrome import CHROME_DOWNLOAD_URL, find_chrome
from account_cleaner.core.log_setup import setup_logging
from account_cleaner.core.paths import resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.pipeline import ImportOutcome
from account_cleaner.storage import Database, StatusStore
from account_cleaner.ui.agent_page import AgentPage
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage
from account_cleaner.ui.errors import install_excepthook, show_exception
from account_cleaner.ui.main_window import APP_TITLE, MainWindow, PageId
from account_cleaner.ui.sources_page import SourcesPage
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
    parser.add_argument(
        "--import-file", type=Path, nargs="+", help="실행 후 로컬 메일 파일 가져오기"
    )
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


def show_import_result(
    window: MainWindow,
    inventory: InventoryPage,
    outcome: ImportOutcome,
    store: StatusStore | None = None,
) -> None:
    """메일 가져오기·분석이 끝나면 후보를 인벤토리에 채우고 그 화면으로 이동한다.
    전에 사용자가 정한 상태(확정·제외 등)가 저장돼 있으면 그대로 보여 준다."""
    statuses = {}
    if store is not None:
        for domain, value in store.labels().items():
            if value in CandidateStatus._value2member_map_:
                statuses[domain] = CandidateStatus(value)
    inventory.set_candidates(outcome.candidates, statuses)
    inventory.detail.set_mail_lookup(outcome.mail_lookup())
    window.show_page(PageId.INVENTORY)


def start_agent_for(
    window: MainWindow,
    inventory: InventoryPage,
    agent_page: AgentPage,
    candidate: AccountCandidate,
    store: StatusStore | None = None,
) -> None:
    """후보 상세의 'AI 에이전트로 탈퇴 진행' → 에이전트 화면으로 가서 그 서비스 안내 시작."""
    playbook = agent_page.playbook_for_domain(candidate.domain)
    if playbook is None:
        return
    window.show_page(PageId.AGENT)
    if agent_page.start_for(playbook.id):
        agent_page.current_domain = candidate.domain  # 결과를 이 후보에 기록
        inventory.set_status(candidate.domain, CandidateStatus.IN_PROGRESS)
        if store is not None:
            store.agent_started(candidate.domain, candidate.service)


def record_agent_result(agent_page: AgentPage, store: StatusStore, event: AgentEvent) -> None:
    """후보에서 시작한 안내가 끝나면 결과를 기록한다 (탈퇴 화면 도착이면 재알림 예약)."""
    domain = agent_page.current_domain
    if domain is None:
        return
    store.agent_finished(domain, event.status.value, reached=event.status is AgentStatus.REACHED)
    agent_page.current_domain = None


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
    store = StatusStore(Database(paths.database))
    agent_page = AgentPage(paths.browser_profile)
    agent_page.run_finished.connect(lambda event: record_agent_result(agent_page, store, event))
    inventory = InventoryPage()
    inventory.detail.set_playbook_lookup(agent_page.playbook_for_domain)
    window.top_bar.search_changed.connect(inventory.set_search)
    inventory.agent_requested.connect(
        lambda candidate: start_agent_for(window, inventory, agent_page, candidate, store)
    )
    sources = SourcesPage(paths.root)
    sources.import_finished.connect(
        lambda outcome: show_import_result(window, inventory, outcome, store)
    )
    inventory.status_changed.connect(
        lambda domain, service, status: store.set_label(domain, service, status.value)
    )
    window.set_page(PageId.SOURCES, sources)
    window.set_page(PageId.INVENTORY, inventory)
    window.set_page(PageId.AGENT, agent_page)
    app.aboutToQuit.connect(BackgroundTask.shutdown_all)
    window.show()
    QTimer.singleShot(0, lambda: warn_if_chrome_missing(window))
    if args.import_file:
        QTimer.singleShot(0, lambda: sources.start_files(args.import_file))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
