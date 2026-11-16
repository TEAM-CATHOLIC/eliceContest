"""메일 소스 연결 화면과 가져오기·분석 파이프라인 테스트. 메일은 합성 MBOX."""

import pytest
from test_mail_import import mbox_of, raw_mail

from account_cleaner.contracts import AnalysisCancelled
from account_cleaner.fakes import FakeAnalyzer
from account_cleaner.mail import ImportCancelled
from account_cleaner.pipeline import Stage, run_pipeline
from account_cleaner.ui.sources_page import SourcesPage, file_opener
from account_cleaner.ui.workers import BackgroundTask

MAILS = [
    raw_mail(message_id="<1@x>", subject="[샘플쇼핑] 카카오로 가입을 환영합니다"),
    raw_mail(message_id="<2@x>", subject="주문하신 상품이 배송되었습니다"),
    raw_mail(
        message_id="<3@x>",
        sender="음악 <no-reply@music.example.net>",
        subject="이메일 인증을 완료해 주세요",
    ),
]


@pytest.fixture
def mbox(tmp_path):
    path = tmp_path / "takeout.mbox"
    path.write_bytes(mbox_of(*MAILS))
    return path


# --- 파이프라인 ---


def test_파일을_가져와_분석하면_후보와_근거_메일_조회가_나온다(mbox):
    # given
    stages = []

    # when
    outcome = run_pipeline(
        file_opener([mbox]), FakeAnalyzer(), lambda s, d, t: stages.append(s), lambda: False
    )

    # then
    assert len(outcome.mails) == 3
    assert {c.domain for c in outcome.candidates} == {"shop.example.com", "music.example.net"}
    evidence = outcome.candidates[0].evidence[0]
    assert outcome.mail_lookup()(evidence.mail_id) is not None
    assert [s for i, s in enumerate(stages) if i == 0 or stages[i - 1] != s] == list(Stage)


def test_가져오는_중에_취소하면_ImportCancelled(mbox):
    # given / when / then
    with pytest.raises(ImportCancelled):
        run_pipeline(file_opener([mbox]), FakeAnalyzer(), lambda *a: None, lambda: True)


def test_분석_중에_취소하면_AnalysisCancelled(mbox):
    # given: 가져오기가 끝난 뒤부터 취소
    stages = []

    def on_stage(stage, done, total):
        stages.append(stage)

    # when / then
    with pytest.raises(AnalysisCancelled):
        run_pipeline(file_opener([mbox]), FakeAnalyzer(), on_stage, lambda: Stage.ANALYZE in stages)


def test_소스를_닫는_정리_함수는_가져오기가_실패해도_부른다():
    # given: 메일 대신 오류를 내는 소스
    cleaned = []

    class Broken:
        name = "broken"

        def total(self):
            return None

        def __iter__(self):
            raise OSError("network")

        def failures(self):
            return []

    # when / then
    with pytest.raises(OSError):
        run_pipeline(
            lambda _c: (Broken(), lambda: cleaned.append(True)),
            FakeAnalyzer(),
            lambda *a: None,
            lambda: False,
        )
    assert cleaned == [True]


# --- 화면 ---


@pytest.fixture
def page(qtbot, tmp_path):
    widget = SourcesPage(tmp_path, analyzer_factory=FakeAnalyzer)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.cancel()
    BackgroundTask.shutdown_all()


def test_파일을_고르고_가져오면_결과_시그널과_요약이_나온다(qtbot, page, mbox):
    # given
    page.file_card.set_paths([mbox])

    # when
    with qtbot.waitSignal(page.import_finished, timeout=5000) as blocker:
        page.file_card.import_button.click()

    # then
    outcome = blocker.args[0]
    assert len(outcome.candidates) == 2
    assert "메일 3통에서 계정 후보 2개" in page.message_label.text()
    qtbot.waitUntil(lambda: page.gmail_button.isEnabled(), timeout=3000)


def test_지원하지_않는_파일이면_시작하지_않고_이유를_보여_준다(page, tmp_path):
    # given: 빈 폴더
    empty = tmp_path / "empty"
    empty.mkdir()

    # when
    page.start_files([empty])

    # then
    assert not page.is_running()
    assert "MBOX·EML" in page.message_label.text()


def test_Gmail_설정_파일이_없으면_실패_이유를_안내한다(qtbot, page, monkeypatch):
    # given: 클라이언트 ID 파일이 어디에도 없음
    monkeypatch.delenv("ACCOUNT_CLEANER_GOOGLE_CLIENT_SECRET", raising=False)

    # when
    with qtbot.waitSignal(page._relay.stage, timeout=3000):
        page.gmail_button.click()
    qtbot.waitUntil(lambda: page.message_label.text() != "", timeout=3000)

    # then
    assert "클라이언트 ID" in page.message_label.text()


def test_가져오는_동안에는_다른_가져오기를_시작할_수_없다(qtbot, page, mbox):
    # given
    page.file_card.set_paths([mbox])

    # when
    with qtbot.waitSignal(page.import_finished, timeout=5000):
        page.file_card.import_button.click()
        running = (page.gmail_button.isEnabled(), page.cancel_button.isEnabled())

    # then
    assert running == (False, True)


def test_가져오기가_끝나면_인벤토리에_후보와_근거_메일이_채워지고_그_화면으로_간다(qtbot, mbox):
    # given
    from account_cleaner.main import show_import_result
    from account_cleaner.ui.candidates.page import InventoryPage
    from account_cleaner.ui.main_window import MainWindow, PageId

    window = MainWindow()
    qtbot.addWidget(window)
    inventory = InventoryPage()
    window.set_page(PageId.INVENTORY, inventory)
    outcome = run_pipeline(file_opener([mbox]), FakeAnalyzer(), lambda *a: None, lambda: False)

    # when
    show_import_result(window, inventory, outcome)
    inventory.select_row(0)

    # then
    assert window.current_page() is PageId.INVENTORY
    assert inventory.model.rowCount() == 2
    first_evidence = inventory.detail.evidence_list.item(0).text()
    assert "메일 <" not in first_evidence  # ID가 아니라 실제 메일 제목이 보임
