"""계정 후보·근거 메일 저장 테스트 (#7, #52). 근거 메일만, 앞부분만, 암호화해서 남는지 본다."""

import sqlite3
from datetime import UTC, datetime

import pytest

from account_cleaner.contracts import (
    AccountCandidate,
    Evidence,
    EvidenceType,
    LoginMethod,
    ParsedMail,
)
from account_cleaner.storage import Database, InventoryStore
from account_cleaner.storage.crypto import KEY_BYTES, FieldCipher
from account_cleaner.storage.db import MIGRATIONS
from account_cleaner.storage.inventory import PREVIEW_CHARS

KEY = b"k" * KEY_BYTES
WHEN = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)


def mail(mail_id: str, sender: str, subject: str, body: str = "본문") -> ParsedMail:
    return ParsedMail(
        id=mail_id,
        sender=sender,
        sender_domain=sender.rpartition("@")[2],
        subject=subject,
        date=WHEN,
        body_text=body,
    )


def candidate(domain: str, *evidence: Evidence, method: LoginMethod | None = None):
    return AccountCandidate(
        service=domain.split(".")[0].title(),
        domain=domain,
        score=0.9,
        evidence=evidence,
        first_seen=WHEN,
        last_seen=WHEN,
        confirmed_login_method=method,
    )


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "app.sqlite3")
    yield database
    database.close()


@pytest.fixture
def mails():
    return {
        "m1": mail("m1", "noreply@github.com", "GitHub 가입을 환영합니다", "가" * 1000),
        "m2": mail("m2", "security@github.com", "새 기기 로그인"),
        "m3": mail("m3", "news@dropbox.com", "Dropbox 계정 확인"),
        "m9": mail("m9", "friend@example.com", "근거가 아닌 개인 메일", "비밀 이야기"),
    }


@pytest.fixture
def candidates():
    return [
        candidate(
            "github.com",
            Evidence("m1", EvidenceType.SIGNUP, 0.97),
            Evidence("m2", EvidenceType.SECURITY, 0.8),
            method=LoginMethod.EMAIL,
        ),
        candidate("dropbox.com", Evidence("m3", EvidenceType.SIGNUP, 0.6)),
    ]


def test_새_DB는_후보와_근거_메일_표까지_만들어진다(db):
    # when
    tables = {
        r[0] for r in db.connection().execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    # then
    assert db.schema_version() == len(MIGRATIONS) == 2
    assert {"candidates", "evidence", "evidence_mails", "inventory_meta"} <= tables


def test_버전1_DB는_사용자_확인을_지우지_않고_버전2로_올라간다(tmp_path):
    # given
    path = tmp_path / "app.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(MIGRATIONS[0] + "PRAGMA user_version = 1;")
    conn.execute(
        "INSERT INTO user_labels VALUES ('github.com', 'GitHub', 'confirmed', '2026-11-01')"
    )
    conn.commit()
    conn.close()

    # when
    db = Database(path)

    # then
    assert db.schema_version() == 2
    assert db.connection().execute("SELECT status FROM user_labels").fetchone()[0] == "confirmed"
    db.close()


def test_저장했다가_다시_읽으면_후보가_같은_순서와_값으로_돌아온다(db, candidates, mails):
    # given
    InventoryStore(db, FieldCipher(KEY)).save("Gmail", candidates, mails)

    # when
    saved = InventoryStore(db, FieldCipher(KEY)).load()

    # then
    assert saved is not None
    assert saved.source_name == "Gmail"
    assert saved.candidates == candidates
    assert not saved.mails_lost


def test_근거로_쓰인_메일만_남고_다른_메일은_저장하지_않는다(db, candidates, mails):
    # when
    count = InventoryStore(db, FieldCipher(KEY)).save("Gmail", candidates, mails)
    saved = InventoryStore(db, FieldCipher(KEY)).load()

    # then
    assert count == 3
    assert set(saved.mails) == {"m1", "m2", "m3"}
    assert saved.mail_lookup()("m9") is None


def test_본문은_앞부분만_남기고_잘렸으면_끝에_말줄임표를_붙인다(db, candidates, mails):
    # when
    InventoryStore(db, FieldCipher(KEY)).save("Gmail", candidates, mails)
    saved = InventoryStore(db, FieldCipher(KEY)).load()

    # then
    assert saved.mails["m1"].body_text == "가" * PREVIEW_CHARS + "…"
    assert saved.mails["m2"].body_text == "본문"
    assert saved.mails["m1"].sender == "noreply@github.com"
    assert saved.mails["m1"].sender_domain == "github.com"
    assert saved.mails["m1"].subject == "GitHub 가입을 환영합니다"
    assert saved.mails["m1"].date == WHEN


def test_DB_파일에는_보낸_사람_제목_본문이_평문으로_남지_않는다(db, candidates, mails):
    # given
    InventoryStore(db, FieldCipher(KEY)).save("Gmail", candidates, mails)
    db.close()

    # when
    raw = db.path.read_bytes()

    # then
    for text in ("noreply@github.com", "GitHub 가입을 환영합니다", "가가가가", "새 기기 로그인"):
        assert text.encode() not in raw
    assert "비밀 이야기".encode() not in raw


def test_다시_가져오면_이전_후보와_근거_메일을_모두_바꾼다(db, candidates, mails):
    # given
    store = InventoryStore(db, FieldCipher(KEY))
    store.save("Gmail", candidates, mails)

    # when
    store.save("파일", candidates[1:], mails)
    saved = store.load()

    # then
    assert saved.source_name == "파일"
    assert [c.domain for c in saved.candidates] == ["dropbox.com"]
    assert set(saved.mails) == {"m3"}


def test_키가_바뀌면_근거_메일만_지우고_후보는_그대로_보여준다(db, candidates, mails):
    # given
    InventoryStore(db, FieldCipher(KEY)).save("Gmail", candidates, mails)

    # when
    saved = InventoryStore(db, FieldCipher(b"x" * KEY_BYTES)).load()

    # then
    assert saved.mails_lost
    assert saved.mails == {}
    assert saved.candidates == candidates
    assert db.connection().execute("SELECT COUNT(*) FROM evidence_mails").fetchone()[0] == 0


def test_키를_둘_곳이_없으면_후보만_저장하고_근거_메일은_남기지_않는다(db, candidates, mails):
    # given
    store = InventoryStore(db, cipher=None)

    # when
    count = store.save("Gmail", candidates, mails)
    saved = store.load()

    # then
    assert count == 0 and not store.encrypts_mail
    assert saved.candidates == candidates
    assert saved.mails == {} and not saved.mails_lost


def test_저장한_적이_없으면_None이고_지우면_다시_None이다(db, candidates, mails):
    # given
    store = InventoryStore(db, FieldCipher(KEY))
    assert store.load() is None
    store.save("Gmail", candidates, mails)

    # when
    store.clear()

    # then
    assert store.load() is None


# --- 화면 연결 ---


def run_file_import(tmp_path):
    from test_mail_import import mbox_of, raw_mail

    from account_cleaner.fakes import FakeAnalyzer
    from account_cleaner.pipeline import run_pipeline
    from account_cleaner.ui.sources_page import file_opener

    mbox = tmp_path / "a.mbox"
    mbox.write_bytes(mbox_of(raw_mail(subject="[샘플쇼핑] 가입을 환영합니다")))
    return run_pipeline(file_opener([mbox]), FakeAnalyzer(), lambda *a: None, lambda: False)


def test_가져온_결과는_저장되고_앱을_다시_켜면_후보와_근거_미리보기가_그대로_보인다(
    qtbot, db, tmp_path
):
    # given: 가져오기 결과를 화면에 보여 주며 저장
    from account_cleaner.main import restore_inventory, show_import_result
    from account_cleaner.storage import StatusStore
    from account_cleaner.ui.candidates.page import InventoryPage
    from account_cleaner.ui.main_window import MainWindow, PageId

    outcome = run_file_import(tmp_path)
    window, first = MainWindow(), InventoryPage()
    qtbot.addWidget(window)
    window.set_page(PageId.INVENTORY, first)
    show_import_result(
        window, first, outcome, StatusStore(db), InventoryStore(db, FieldCipher(KEY))
    )
    StatusStore(db).set_label("shop.example.com", "샘플쇼핑", "confirmed")

    # when: 새 화면(다시 켠 앱)에서 복원
    restored = InventoryPage()
    qtbot.addWidget(restored)
    saved = InventoryStore(db, FieldCipher(KEY)).load()
    ok = restore_inventory(restored, saved, StatusStore(db))
    restored.select_row(0)

    # then
    from account_cleaner.ui.candidates.model import CandidateStatus

    assert ok
    assert restored.visible_candidates() == outcome.candidates
    assert restored.model.status_of("shop.example.com") is CandidateStatus.CONFIRMED
    restored.detail.evidence_list.setCurrentRow(0)
    assert "[샘플쇼핑] 가입을 환영합니다" in restored.detail.preview.toPlainText()


def test_저장한_적이_없으면_복원하지_않는다(qtbot):
    # given
    from account_cleaner.main import restore_inventory
    from account_cleaner.ui.candidates.page import InventoryPage

    page = InventoryPage()
    qtbot.addWidget(page)

    # when / then
    assert restore_inventory(page, None) is False
    assert page.visible_candidates() == []


def test_키를_둘_곳이_있으면_사이드바에_암호화_적용을_표시한다(db, tmp_path, monkeypatch):
    # given: 키체인 대신 키 파일
    from account_cleaner.main import encryption_status, open_inventory_store

    monkeypatch.setenv("ACCOUNT_CLEANER_KEY_STORE", "file")

    # when
    store, key = open_inventory_store(db, tmp_path / "evidence.key")

    # then
    assert store.encrypts_mail
    assert encryption_status(key) == "적용 (메일 근거, 키 파일)"
    assert (tmp_path / "evidence.key").is_file()


def test_키를_둘_곳이_없으면_근거_메일_없이_후보만_저장하고_미적용으로_표시한다(
    db, tmp_path, monkeypatch
):
    # given
    import account_cleaner.main as app_main
    from account_cleaner.storage.crypto import KeyStoreUnavailable

    def unavailable(_stores):
        raise KeyStoreUnavailable("없음")

    monkeypatch.setattr(app_main, "load_or_create_key", unavailable)

    # when
    store, key = app_main.open_inventory_store(db, tmp_path / "evidence.key")

    # then
    assert key is None and not store.encrypts_mail
    assert app_main.encryption_status(key).startswith("미적용")
