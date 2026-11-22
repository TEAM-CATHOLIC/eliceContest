import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle, QSystemTrayIcon, QWidget

from account_cleaner import providers
from account_cleaner.browser.agent.llm import api_key_source
from account_cleaner.contracts import AccountCandidate, AgentEvent, AgentStatus, ParsedMail
from account_cleaner.core.chrome import CHROME_DOWNLOAD_URL, find_chrome
from account_cleaner.core.log_setup import setup_logging
from account_cleaner.core.paths import resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.pipeline import ImportOutcome
from account_cleaner.storage import Database, InventoryStore, SavedInventory, StatusStore
from account_cleaner.storage.crypto import (
    KeySource,
    KeyStoreUnavailable,
    LoadedKey,
    default_key_stores,
    load_or_create_key,
)
from account_cleaner.ui.agent_page import AgentPage
from account_cleaner.ui.api_key_dialog import ApiKeyDialog, ai_status_text
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage
from account_cleaner.ui.errors import install_excepthook, show_exception
from account_cleaner.ui.history_page import HistoryPage
from account_cleaner.ui.main_window import APP_TITLE, MainWindow, PageId
from account_cleaner.ui.session_cleaner import SessionCleaner
from account_cleaner.ui.sources_page import SourcesPage
from account_cleaner.ui.theme import apply_theme
from account_cleaner.ui.theme.icons import app_icon
from account_cleaner.ui.workers import BackgroundTask

ORGANIZATION = "TEAM-CATHOLIC"
APPLICATION = "AccountCleaner"

log = logging.getLogger(__name__)

ENCRYPTION_STATUS = "엔진 암호화"
MAILS_LOST_TEXT = (
    "암호화 키가 바뀌어 저장해 둔 근거 메일을 열 수 없어 지웠습니다. "
    "계정 후보는 그대로 있습니다. 근거 메일 내용을 보려면 메일을 다시 불러오세요."
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="account-cleaner")
    parser.add_argument(
        "--self-test", action="store_true", help="창 없이 묶인 구성요소를 확인하고 종료"
    )
    parser.add_argument("--require-chrome", action="store_true", help="Chrome이 없으면 실패")
    parser.add_argument(
        "--require-model", action="store_true", help="AI 모델이 묶여 있지 않으면 실패"
    )
    parser.add_argument("--report", type=Path, help="self-test 결과를 쓸 파일")
    parser.add_argument(
        "--import-file", type=Path, nargs="+", help="실행 후 로컬 메일 파일 가져오기"
    )
    # macOS가 붙이는 -psn_* 같은 인자와 Qt 인자는 무시한다.
    args, _ = parser.parse_known_args(argv)
    return args


def self_test(args: argparse.Namespace) -> int:
    from account_cleaner.core.self_test import run_self_test

    checks = run_self_test(require_chrome=args.require_chrome, require_model=args.require_model)
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


def saved_statuses(store: StatusStore | None) -> dict[str, CandidateStatus]:
    """전에 사용자가 정한 상태(확정·제외 등)."""
    if store is None:
        return {}
    return {
        domain: CandidateStatus(value)
        for domain, value in store.labels().items()
        if value in CandidateStatus._value2member_map_
    }


def show_import_result(
    window: MainWindow,
    inventory: InventoryPage,
    outcome: ImportOutcome,
    store: StatusStore | None = None,
    inventory_store: InventoryStore | None = None,
    agent_page: AgentPage | None = None,
) -> None:
    """메일 가져오기·분석이 끝나면 후보를 인벤토리에 채우고 그 화면으로 이동한다.
    후보와 근거 메일(암호화, 앞부분만)을 저장해 다음 실행 때 다시 보여 준다."""
    inventory.set_candidates(outcome.candidates, saved_statuses(store))
    inventory.detail.set_mail_lookup(outcome.mail_lookup())
    update_completion_evidence(inventory, outcome.mails, store)
    if agent_page is not None:
        agent_page.set_private_values(outcome.private_values)
    window.show_page(PageId.INVENTORY)
    if inventory.detail.completion_results:
        window.statusBar().showMessage(
            "탈퇴 완료 표현이 있는 새 메일을 발견했습니다. 후보 상세에서 근거를 확인하세요.", 20_000
        )
    if inventory_store is not None:
        by_id = {m.id: m for m in outcome.mails}
        count = inventory_store.save(outcome.source_name, outcome.candidates, by_id)
        log.info("후보 %d개와 근거 메일 %d통 저장", len(outcome.candidates), count)


def restore_inventory(
    inventory: InventoryPage,
    saved: SavedInventory | None,
    store: StatusStore | None = None,
) -> bool:
    """지난번에 저장한 후보를 인벤토리에 채운다. 저장한 것이 없으면 False."""
    if saved is None:
        return False
    inventory.set_candidates(saved.candidates, saved_statuses(store))
    inventory.detail.set_mail_lookup(saved.mail_lookup())
    update_completion_evidence(inventory, list(saved.mails.values()), store)
    return True


def update_completion_evidence(
    inventory: InventoryPage, mails: list[ParsedMail], store: StatusStore | None
) -> None:
    """이번 안내 후의 메일 근거만 표시한다. 완료 상태·재알림·세션은 바꾸지 않는다."""
    from account_cleaner.classifier.completion import find_completion

    inventory.known_mail_ids = {m.id for m in mails}
    results = {}
    by_id = {m.id: m for m in mails}
    if store is not None:
        for progress in store.all_progress():
            watch = store.completion_watch(progress.domain)
            if watch is None:
                continue
            started_at, known_ids = watch
            evidence = find_completion(mails, progress.domain, started_at, known_ids)
            if evidence is not None:
                results[progress.domain] = (by_id[evidence.mail_id], evidence.statement)
    inventory.detail.set_completion_results(results)


def open_inventory_store(db: Database, key_file: Path) -> tuple[InventoryStore, LoadedKey | None]:
    """근거 메일 암호화 키를 불러온다. 키를 둘 곳이 없으면 근거 메일 없이 후보만 저장한다."""
    try:
        key = load_or_create_key(default_key_stores(key_file))
    except KeyStoreUnavailable:
        log.warning("암호화 키를 둘 곳이 없어 근거 메일은 저장하지 않습니다")
        return InventoryStore(db, cipher=None), None
    log.info("근거 메일 암호화 키: %s%s", key.source.label, " (새로 만듦)" if key.created else "")
    return InventoryStore(db, key.cipher()), key


CLEAR_LOGINS_QUESTION = (
    "에이전트 전용 Chrome에 저장된 로그인을 모두 지울까요?\n\n"
    "다음 안내 때 서비스마다 다시 로그인해야 합니다. 평소 쓰는 Chrome의 로그인은 그대로입니다."
)


def record_status(
    store: StatusStore,
    cleaner: SessionCleaner | None,
    domain: str,
    service: str,
    status: CandidateStatus,
) -> None:
    """사용자 확인을 저장한다. '탈퇴를 끝냈어요'(완료)면 그 서비스 세션을 바로 지운다 (D-05)."""
    store.set_label(domain, service, status.value)
    if status is CandidateStatus.DONE:
        store.mark_completed(domain)
        if cleaner is not None:
            cleaner.clear_due()


AI_STATUS = "AI 안내"


def open_api_key_dialog(window: MainWindow, inventory: InventoryPage) -> ApiKeyDialog:
    """사이드바 `AI 키 설정`. 키를 바꾸면 상태 줄과 상세 패널 버튼을 다시 계산한다 (#81)."""
    dialog = ApiKeyDialog(window)

    def changed() -> None:
        window.sidebar_footer.set_status(AI_STATUS, ai_status_text(api_key_source()))
        inventory.refresh_detail()

    dialog.key_changed.connect(changed)
    dialog.open()
    return dialog


def confirm_clear_logins(
    window: QWidget,
    cleaner: SessionCleaner,
    ask: Callable[[QWidget, str], bool] | None = None,
) -> bool:
    """사이드바 '저장된 로그인 모두 지우기'. 확인을 받은 뒤에만 지운다."""
    ask = ask or ask_yes_no
    if not ask(window, CLEAR_LOGINS_QUESTION):
        return False
    return cleaner.clear_all()


def ask_yes_no(parent: QWidget, text: str) -> bool:
    answer = QMessageBox.question(
        parent, "저장된 로그인 지우기", text, defaultButton=QMessageBox.StandardButton.No
    )
    return answer == QMessageBox.StandardButton.Yes


def show_cleanup_result(window: MainWindow, domains: list[str]) -> None:
    if domains == [SessionCleaner.ALL]:
        window.statusBar().showMessage("저장된 로그인을 모두 지웠습니다.", 10_000)
    else:
        window.statusBar().showMessage(
            f"탈퇴를 마쳤거나 오래된 로그인 {len(domains)}곳을 지웠습니다.", 10_000
        )


def restart_from_history(
    window: MainWindow,
    inventory: InventoryPage,
    agent_page: AgentPage,
    store: StatusStore,
    domain: str,
) -> None:
    """재알림의 '다시 안내 시작'. 인벤토리에 후보가 없어도(메일을 다시 안 불러옴) 플레이북으로 시작한다."""
    candidate = inventory.model.candidate_of(domain)
    if candidate is not None:
        start_agent_for(window, inventory, agent_page, candidate, store)
        return
    playbook = agent_page.playbook_for_domain(domain)
    if playbook is None:
        return
    window.show_page(PageId.AGENT)
    if agent_page.start_for(playbook.id):
        agent_page.current_domain = domain
        store.agent_started(domain, playbook.service)


def complete_from_history(
    inventory: InventoryPage,
    store: StatusStore,
    cleaner: SessionCleaner | None,
    history: HistoryPage,
    domain: str,
) -> None:
    """재알림의 '탈퇴를 끝냈어요'. 인벤토리에 후보가 있으면 목록 상태도 함께 바꾼다."""
    if inventory.model.service_of(domain) is not None:
        inventory.set_status(domain, CandidateStatus.DONE)  # → status_changed → record_status
    else:
        progress = store.progress(domain)
        service = progress.service if progress else domain
        record_status(store, cleaner, domain, service, CandidateStatus.DONE)
    history.refresh()


def reminder_message(store: StatusStore) -> str | None:
    """앱을 켰을 때 알릴 문장. 알릴 서비스가 없으면 None."""
    due = store.due_reminders()
    if not due:
        return None
    services = {p.domain: p.service for p in store.all_progress()}
    first = services.get(due[0], due[0])
    more = f" 외 {len(due) - 1}곳" if len(due) > 1 else ""
    return f"{first}{more}의 탈퇴를 아직 끝내지 않았어요. 진행 기록에서 확인해 주세요."


def notify_reminders(window: MainWindow, store: StatusStore) -> QSystemTrayIcon | None:
    """재알림 대상이 있으면 시스템 알림을 띄우고 진행 기록 화면을 연다 (F-08)."""
    text = reminder_message(store)
    if text is None:
        return None
    window.show_page(PageId.HISTORY)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        window.statusBar().showMessage(text, 30_000)
        return None
    icon = window.windowIcon()
    if icon.isNull():
        icon = window.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
    tray = QSystemTrayIcon(icon, window)
    tray.setToolTip(APP_TITLE)
    tray.messageClicked.connect(lambda: window.show_page(PageId.HISTORY))
    tray.show()
    tray.showMessage("탈퇴 마무리 알림", text)
    return tray


def encryption_status(key: LoadedKey | None) -> str:
    if key is None:
        return "미적용 (근거 메일 저장 안 함)"
    if key.source is KeySource.FILE:
        return "적용 (메일 근거, 키 파일)"
    return "적용 (메일 근거)"


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
            store.agent_started(candidate.domain, candidate.service, inventory.known_mail_ids)
            inventory.detail.clear_completion_result(candidate.domain)


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
    app.setWindowIcon(app_icon())
    apply_theme(app)

    try:
        paths = resolve_app_paths()
    except (OSError, RuntimeError) as e:
        show_exception(None, e, "앱 데이터 폴더를 만들 수 없습니다.")
        return 1

    setup_logging(paths.logs)
    install_excepthook()
    log.info("앱 시작 (데이터 폴더: %s)", paths.root)

    window = MainWindow(AppSettings(paths.settings_file))
    database = Database(paths.database)
    store = StatusStore(database)
    inventory_store, key = open_inventory_store(database, paths.key_file)
    window.sidebar_footer.set_status(ENCRYPTION_STATUS, encryption_status(key))
    agent_page = AgentPage(paths.browser_profile)
    agent_page.run_finished.connect(lambda event: record_agent_result(agent_page, store, event))
    agent_page.running_changed.connect(
        lambda running: window.set_nav_badge(PageId.AGENT, "진행" if running else None)
    )
    cleaner = SessionCleaner(
        store,
        paths.browser_profile,
        agent_factory=providers.get_withdraw_agent,
        playbook_lookup=agent_page.playbook_for_domain,
        agent_busy=agent_page.is_running,
        parent=window,
    )
    agent_page.run_finished.connect(lambda _event: cleaner.retry_pending())
    cleaner.cleared.connect(lambda domains: show_cleanup_result(window, domains))
    cleaner.failed.connect(lambda text: window.statusBar().showMessage(text, 15_000))
    window.sidebar_footer.set_status(AI_STATUS, ai_status_text(api_key_source()))
    window.sidebar_footer.api_key_requested.connect(lambda: open_api_key_dialog(window, inventory))
    window.sidebar_footer.clear_logins_requested.connect(
        lambda: confirm_clear_logins(window, cleaner)
    )
    inventory = InventoryPage()
    inventory.detail.set_playbook_lookup(agent_page.playbook_for_domain)
    window.top_bar.search_changed.connect(inventory.set_search)
    agent_page.set_candidate_lookup(inventory.model.candidate_of)
    inventory.agent_requested.connect(
        lambda candidate: start_agent_for(window, inventory, agent_page, candidate, store)
    )
    sources = SourcesPage(paths.root)
    sources.import_finished.connect(
        lambda outcome: show_import_result(
            window, inventory, outcome, store, inventory_store, agent_page
        )
    )
    saved = inventory_store.load()
    restore_inventory(inventory, saved, store)
    inventory.status_changed.connect(
        lambda domain, service, status: record_status(store, cleaner, domain, service, status)
    )
    window.set_page(PageId.SOURCES, sources)
    window.set_page(PageId.INVENTORY, inventory)
    window.set_page(PageId.AGENT, agent_page)
    history = HistoryPage(store)
    window.set_page(PageId.HISTORY, history)
    history.restart_requested.connect(
        lambda domain: restart_from_history(window, inventory, agent_page, store, domain)
    )
    history.done_requested.connect(
        lambda domain: complete_from_history(inventory, store, cleaner, history, domain)
    )
    agent_page.run_finished.connect(lambda _event: history.refresh())
    cleaner.cleared.connect(lambda _domains: history.refresh())
    app.aboutToQuit.connect(BackgroundTask.shutdown_all)
    window.show()
    QTimer.singleShot(0, lambda: warn_if_chrome_missing(window))
    QTimer.singleShot(0, cleaner.clear_due)  # 보관 기한(14일)이 지난 세션
    QTimer.singleShot(0, lambda: notify_reminders(window, store))
    if saved is not None and saved.mails_lost:
        QTimer.singleShot(0, lambda: QMessageBox.information(window, "근거 메일", MAILS_LOST_TEXT))
    if args.import_file:
        QTimer.singleShot(0, lambda: sources.start_files(args.import_file))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
