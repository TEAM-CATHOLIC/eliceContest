from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from account_cleaner.contracts import AccountCandidate, Evidence, EvidenceType, ParsedMail
from account_cleaner.mail import ImportStats
from account_cleaner.main import (
    restore_inventory,
    show_import_result,
    start_agent_for,
    update_completion_evidence,
)
from account_cleaner.pipeline import ImportOutcome
from account_cleaner.storage import Database, InventoryStore, StatusStore
from account_cleaner.storage.crypto import FieldCipher
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage
from account_cleaner.ui.main_window import MainWindow, PageId

T = datetime(2026, 11, 19, tzinfo=UTC)
DOMAIN = "dropbox.com"


def message(body="회원 탈퇴 처리가 완료되었습니다.", key="new", domain=DOMAIN, date=None):
    return ParsedMail(
        key, f"notice@{domain}", domain, "탈퇴 안내", date or T + timedelta(seconds=1), body
    )


def candidate(key="new"):
    return AccountCandidate(
        "Dropbox", DOMAIN, 0.1, (Evidence(key, EvidenceType.DELETED, 1.0),), T, T
    )


@pytest.fixture
def setup(qtbot, tmp_path):
    now = [T]
    db = Database(tmp_path / "app.sqlite3", clock=lambda: now[0])
    store = StatusStore(db)
    page = InventoryPage()
    qtbot.addWidget(page)
    page.set_candidates([candidate()], {DOMAIN: CandidateStatus.IN_PROGRESS})
    page.select_row(0)
    yield db, store, page, now
    db.close()


def test_mail_evidence_does_not_complete_or_clear_sessions(setup):
    _db, store, page, _now = setup
    store.agent_started(DOMAIN, "Dropbox", {"old"})
    update_completion_evidence(page, [message()], store)
    assert "완료 표현 메일 발견" in page.detail.completion_label.text()
    assert "사용자 완료 미확인" in page.detail.completion_label.text()
    assert page.model.status_of(DOMAIN) is CandidateStatus.IN_PROGRESS
    assert store.progress(DOMAIN).completed_at is None
    assert store.sessions_to_clear() == []
    page.detail.completion_button.click()
    assert "회원 탈퇴 처리가 완료되었습니다" in page.detail.preview.toPlainText()
    page.set_status(DOMAIN, CandidateStatus.DONE)
    assert "사용자 완료 확인 · 완료 표현 메일 발견" in page.detail.completion_label.text()


@pytest.mark.parametrize(
    "mail",
    [
        message("회원 탈퇴 요청이 접수되었습니다."),
        message("계정은 다음 달 삭제될 예정입니다."),
        message("구독 해지가 완료되었습니다."),
        message("회원 탈퇴가 완료되지 않았습니다."),
        message(domain="other.example"),
        message(date=T - timedelta(days=1)),
        message(key="old"),
    ],
)
def test_non_completion_mail_is_rejected(setup, mail):
    _db, store, page, _now = setup
    store.agent_started(DOMAIN, "Dropbox", {"old"})
    update_completion_evidence(page, [mail], store)
    assert page.detail.completion_results == {}
    assert "완료 메일 미확인" in page.detail.completion_label.text()


def test_retry_resets_watch_and_manual_completion(setup):
    _db, store, page, now = setup
    store.agent_started(DOMAIN, "Dropbox", set())
    store.mark_completed(DOMAIN)
    now[0] += timedelta(days=1)
    store.agent_started(DOMAIN, "Dropbox", {"new"})
    assert store.completion_watch(DOMAIN) == (now[0], {"new"})
    assert store.progress(DOMAIN).completed_at is None
    assert store.progress(DOMAIN).started_at == now[0]
    update_completion_evidence(page, [message()], store)
    assert not page.detail.completion_results


def test_import_and_encrypted_restore_show_evidence(setup, qtbot):
    db, store, page, _now = setup
    store.agent_started(DOMAIN, "Dropbox", set())
    store.set_label(DOMAIN, "Dropbox", CandidateStatus.IN_PROGRESS.value)
    inventory_store = InventoryStore(db, FieldCipher(b"k" * 32))
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_page(PageId.INVENTORY, page)
    outcome = ImportOutcome("EML", [message()], [candidate()], ImportStats())
    show_import_result(window, page, outcome, store, inventory_store)
    assert "새 메일" in window.statusBar().currentMessage()
    restored = InventoryPage()
    qtbot.addWidget(restored)
    assert restore_inventory(restored, inventory_store.load(), StatusStore(db))
    restored.select_row(0)
    assert "완료 표현 메일 발견" in restored.detail.completion_label.text()
    assert restored.model.status_of(DOMAIN) is CandidateStatus.IN_PROGRESS
    page.setParent(None)  # The fixture owns this widget, not the temporary window.


def test_legacy_progress_without_baseline_does_not_guess(setup):
    _db, store, page, _now = setup
    store.agent_started(DOMAIN, "Dropbox")
    update_completion_evidence(page, [message()], store)
    assert not page.detail.completion_results


def test_inventory_start_records_the_mail_baseline(setup, qtbot):
    _db, store, page, _now = setup
    window = MainWindow()
    qtbot.addWidget(window)
    page.known_mail_ids = {"existing"}
    agent = SimpleNamespace(
        playbook_for_domain=lambda _domain: SimpleNamespace(id="dropbox"),
        start_for=lambda _id: True,
    )
    start_agent_for(window, page, agent, candidate(), store)
    assert store.completion_watch(DOMAIN) == (T, {"existing"})
    assert page.model.status_of(DOMAIN) is CandidateStatus.IN_PROGRESS


def test_baseline_survives_database_reopen(tmp_path):
    path = tmp_path / "watch.sqlite3"
    db = Database(path, clock=lambda: T)
    StatusStore(db).agent_started(DOMAIN, "Dropbox", {"existing"})
    db.close()
    db = Database(path)
    assert StatusStore(db).completion_watch(DOMAIN) == (T, {"existing"})
    db.close()
