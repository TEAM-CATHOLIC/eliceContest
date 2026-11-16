"""Gmail 연결 테스트. 네트워크·실제 계정 없이 가짜 API 응답으로만 확인한다."""

import base64
import json
import re
import threading
from datetime import UTC, datetime

import httplib2
import pytest

from account_cleaner.mail import (
    GmailLoginError,
    GmailMailSource,
    GmailSetupError,
    GoogleGmailApi,
    ImportCancelled,
    authorize,
    find_client_secret,
    import_mails,
    load_client_config,
    parse_mail,
)
from account_cleaner.mail.gmail import CLIENT_SECRET_ENV, CLIENT_SECRET_FILE, message_to_bytes

DESKTOP_CLIENT = {
    "installed": {
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "not-a-real-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(
    message_id: str, subject="가입을 환영합니다", sender="샘플쇼핑 <no-reply@shop.example.com>"
):
    """Gmail API `format=full` 응답 모양 (합성)."""
    return {
        "id": message_id,
        "internalDate": "1794618000000",  # 2026-11-14 01:00:00 UTC
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{message_id}@shop.example.com>"},
                {"name": "Content-Type", "value": 'multipart/mixed; boundary="X"'},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "headers": [
                        {"name": "Content-Type", "value": 'multipart/alternative; boundary="Y"'}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "headers": [
                                {"name": "Content-Type", "value": "text/plain; charset=UTF-8"},
                                {"name": "Content-Transfer-Encoding", "value": "quoted-printable"},
                            ],
                            "body": {"data": b64("회원가입이 완료되었습니다.")},
                        },
                        {
                            "mimeType": "text/html",
                            "headers": [
                                {"name": "Content-Type", "value": "text/html; charset=UTF-8"}
                            ],
                            "body": {"data": b64("<p>회원가입이 완료되었습니다.</p>")},
                        },
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "영수증.pdf",
                    "headers": [
                        {"name": "Content-Type", "value": 'application/pdf; name="r.pdf"'},
                        {"name": "Content-Disposition", "value": 'attachment; filename="r.pdf"'},
                    ],
                    "body": {"attachmentId": "ATT1", "size": 120000},
                },
            ],
        },
    }


class HttpError(Exception):
    """googleapiclient HttpError처럼 resp.status와 JSON content를 가진다."""

    def __init__(self, status: int, reason: str | None = None):
        super().__init__(status)
        self.resp = type("Resp", (), {"status": status})()
        errors = [{"reason": reason}] if reason else []
        self.content = json.dumps({"error": {"code": status, "errors": errors}}).encode()


class FakeTime:
    """sleep하면 시계가 그만큼 간다. 실제로 기다리지 않는다."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now


def source_of(api, **kwargs):
    t = FakeTime()
    return GmailMailSource(api, sleep=t.sleep, clock=t.clock, **kwargs), t


class FakeApi:
    """페이지 2개짜리 메일함. `errors`로 메시지별 실패를 순서대로 지정한다."""

    def __init__(self, ids, errors=None, page_size=3):
        self.ids = ids
        self.errors = {k: list(v) for k, v in (errors or {}).items()}
        self.page_size = page_size
        self.batches: list[list[str]] = []

    def profile_email(self):
        return "tester@gmail.com"

    def list_ids(self, page_token, query):
        start = int(page_token or 0)
        end = start + self.page_size
        return self.ids[start:end], (str(end) if end < len(self.ids) else None)

    def get_full(self, ids):
        self.batches.append(list(ids))
        results = {}
        for message_id in ids:
            pending = self.errors.get(message_id)
            if pending:
                error = pending.pop(0)
                results[message_id] = (
                    HttpError(*error) if isinstance(error, tuple) else HttpError(error)
                )
            else:
                results[message_id] = gmail_message(message_id)
        return results


# --- format=full → 원문 ---


def test_Gmail_응답을_원문으로_조립하면_공통_정규화를_그대로_거친다():
    # given
    message = gmail_message("m1")

    # when
    mail = parse_mail(message_to_bytes(message))

    # then
    assert mail.subject == "가입을 환영합니다"
    assert mail.sender == "no-reply@shop.example.com"
    assert mail.body_text == "회원가입이 완료되었습니다."
    assert mail.id == "<m1@shop.example.com>"


def test_Date_헤더가_없으면_Gmail_수신_시각을_쓴다():
    # given: gmail_message에는 Date 헤더가 없음
    message = gmail_message("m1")

    # when
    mail = parse_mail(message_to_bytes(message))

    # then
    assert mail.date == datetime(2026, 11, 14, 1, tzinfo=UTC)


def test_첨부는_본문_없이_조립되어_본문에_들어가지_않는다():
    # given
    raw = message_to_bytes(gmail_message("m1"))

    # when / then
    assert b"ATT1" not in raw
    assert "영수증" not in parse_mail(raw).body_text


# --- 메일 소스 ---


def test_모든_페이지의_메일을_받고_배치는_20통에서_시작해_연속_성공하면_늘린다():
    # given: 120통, 목록 페이지는 50개씩
    api = FakeApi([f"m{i}" for i in range(120)], page_size=50)
    source, _ = source_of(api)

    # when
    result = import_mails(source)

    # then: 20통 3번 성공 → 25통
    assert len(result.mails) == 120
    assert [len(b) for b in api.batches] == [20, 20, 20, 25, 25, 10]
    assert source.name == "Gmail (tester@gmail.com)"


def test_한도에_걸리면_배치를_절반으로_줄인다():
    """회귀: 50통 고정 배치는 동시 요청 한도에 걸려 다시 받기 5번 뒤에도 31통이 빠졌다."""
    # given: 첫 배치(20통) 중 절반이 한 번 429
    ids = [f"m{i}" for i in range(40)]
    api = FakeApi(ids, page_size=500, errors={f"m{i}": [429] for i in range(0, 20, 2)})
    source, _ = source_of(api)

    # when
    result = import_mails(source)

    # then: 걸린 10통이 먼저 10통 배치로 다시 나감
    assert len(result.mails) == 40
    assert [len(b) for b in api.batches[:2]] == [20, 10]
    assert api.batches[1] == [f"m{i}" for i in range(0, 20, 2)]


def test_한도에_계속_걸리는_메일만_8번_뒤_포기하고_나머지는_받는다():
    # given: m1은 계속 429
    api = FakeApi(["m0", "m1", "m2"], errors={"m1": [429] * 20})
    source, _ = source_of(api)

    # when
    result = import_mails(source)

    # then
    assert len(result.mails) == 2
    assert [(s.origin, s.reason) for s in result.stats.skipped] == [
        ("gmail:m1", "요청 한도 초과로 받지 못함")
    ]
    assert sum(b.count("m1") for b in api.batches) == 8


def test_요청_한도_초과는_기다렸다가_다시_받는다():
    # given: m1은 429 두 번 뒤 성공
    api = FakeApi(["m0", "m1", "m2"], errors={"m1": [429, 429]})
    source, t = source_of(api)

    # when
    result = import_mails(source)

    # then: 백오프 1초·2초 (배치 간격 1초는 이미 지나 추가 대기 없음)
    assert len(result.mails) == 3
    assert t.sleeps == [1, 2]
    assert api.batches == [["m0", "m1", "m2"], ["m1"], ["m1"]]


def test_요청이_몰려_받은_403_rateLimitExceeded도_다시_받는다():
    """회귀: 실제 계정에서 두 번째 배치부터 403 rateLimitExceeded로 78통이 빠졌다."""
    # given
    api = FakeApi(["m0", "m1"], errors={"m1": [(403, "rateLimitExceeded")]})
    source, _ = source_of(api)

    # when
    result = import_mails(source)

    # then
    assert len(result.mails) == 2
    assert result.stats.skipped == []


def test_권한_오류인_403은_다시_받지_않는다():
    # given: 이유가 요청 한도가 아닌 403
    api = FakeApi(["m0", "m1"], errors={"m1": [(403, "forbidden")]})
    source, _ = source_of(api)

    # when
    result = import_mails(source)

    # then
    assert len(result.mails) == 1
    assert api.batches == [["m0", "m1"]]


def test_배치_요청_사이에는_최소_1초_간격을_둔다():
    # given: 120통, 각 배치는 시간이 걸리지 않음
    api = FakeApi([f"m{i}" for i in range(120)], page_size=500)
    source, t = source_of(api)

    # when
    import_mails(source)

    # then
    assert t.sleeps == [1.0] * (len(api.batches) - 1)


def test_다시_받아도_안_되는_메일은_건너뛰고_기록한다():
    # given: m1은 사라진 메일(404)
    api = FakeApi(["m0", "m1", "m2"], errors={"m1": [404]})

    # when
    result = import_mails(source_of(api)[0])

    # then
    assert len(result.mails) == 2
    assert [(s.origin, s.reason) for s in result.stats.skipped] == [("gmail:m1", "받기 실패 (404)")]


def test_진행률은_받은_통수로_전체에서_끝난다():
    # given
    api = FakeApi([f"m{i}" for i in range(5)])
    progress = []

    # when
    import_mails(source_of(api)[0], on_progress=lambda d, t: progress.append((d, t)))

    # then
    assert progress[-1] == (5, 5)


def test_최대_통수를_정하면_그만큼만_받는다():
    # given
    api = FakeApi([f"m{i}" for i in range(10)])

    # when
    result = import_mails(GmailMailSource(api, max_messages=4))

    # then
    assert len(result.mails) == 4


def test_목록을_받는_중에_취소하면_ImportCancelled():
    # given
    source = GmailMailSource(FakeApi(["m0"]), should_cancel=lambda: True)

    # when / then
    with pytest.raises(ImportCancelled):
        import_mails(source)


# --- 실제 google-api-python-client 경로 (HTTP만 가짜) ---


class FakeGmailHttp:
    """Gmail REST 응답을 흉내 내는 httplib2 대용. 배치 요청은 multipart로 받아 multipart로 답한다."""

    def __init__(self, ids, statuses=None):
        self.ids = ids
        self.statuses = {k: list(v) for k, v in (statuses or {}).items()}

    @staticmethod
    def _json(payload, status=200):
        return httplib2.Response({"status": str(status)}), json.dumps(payload).encode()

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        if uri.split("?")[0].rstrip("/").endswith("/batch") or "/batch/" in uri:
            return self._batch(body if isinstance(body, str) else body.decode())
        if uri.split("?")[0].endswith("/profile"):
            return self._json({"emailAddress": "tester@gmail.com"})
        if "/messages?" in uri or uri.split("?")[0].endswith("/messages"):
            return self._json({"messages": [{"id": i} for i in self.ids]})
        raise AssertionError(f"예상하지 못한 요청: {method} {uri}")

    def _batch(self, body):
        content_ids = re.findall(r"Content-ID: <(.+?)>", body)
        message_ids = re.findall(r"/messages/([^/?\s]+)\?", body)
        out = ""
        for content_id, message_id in zip(content_ids, message_ids, strict=True):
            pending = self.statuses.get(message_id)
            status = pending.pop(0) if pending else 200
            error = {"code": status, "errors": [{"reason": "rateLimitExceeded"}]}
            payload = gmail_message(message_id) if status == 200 else {"error": error}
            out += (
                "--BATCH\r\nContent-Type: application/http\r\n"
                f"Content-ID: <response-{content_id}>\r\n\r\n"
                f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n\r\n"
                f"{json.dumps(payload)}\r\n"
            )
        out += "--BATCH--"
        headers = {"status": "200", "content-type": "multipart/mixed; boundary=BATCH"}
        return httplib2.Response(headers), out.encode()


def test_실제_Gmail_클라이언트의_배치_요청으로_메일을_받는다():
    """회귀: batch.add의 두 번째 위치 인자는 callback이라 ID를 넘기면 실행 중 터졌다."""
    # given: 3통, m1은 한 번 403 rateLimitExceeded (실제 HttpError 파싱까지 거침)
    api = GoogleGmailApi(http=FakeGmailHttp(["m0", "m1", "m2"], statuses={"m1": [403]}))

    # when
    result = import_mails(source_of(api)[0])

    # then
    assert sorted(m.id for m in result.mails) == [f"<m{i}@shop.example.com>" for i in range(3)]
    assert result.stats.skipped == []


# --- 클라이언트 ID 파일 ---


def test_클라이언트_ID_파일은_환경변수를_앱_데이터_폴더보다_먼저_찾는다(tmp_path):
    # given: 두 곳 모두 파일이 있음
    env_file = tmp_path / "from_env.json"
    env_file.write_text("{}")
    (tmp_path / CLIENT_SECRET_FILE).write_text("{}")

    # when
    found = find_client_secret(tmp_path, env={CLIENT_SECRET_ENV: str(env_file)})

    # then
    assert found == env_file


def test_클라이언트_ID_파일이_어디에도_없으면_설정_안내_오류(tmp_path):
    # given / when / then
    with pytest.raises(GmailSetupError, match=CLIENT_SECRET_FILE):
        find_client_secret(tmp_path / "empty", env={})


def test_데스크톱_앱이_아닌_클라이언트_유형은_거부한다(tmp_path):
    # given: 웹 애플리케이션 유형으로 만든 파일
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"web": {}}))

    # when / then
    with pytest.raises(GmailSetupError, match="데스크톱 앱"):
        load_client_config(path)


# --- 로그인 ---


def test_로그인을_기다리는_중에_취소하면_ImportCancelled():
    # given: 브라우저를 열지 않고 로그인 대기, 0.3초 뒤 취소 요청
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()

    # when / then
    with pytest.raises(ImportCancelled):
        # 시간 제한을 짧게 둬서, 취소가 안 먹으면 5분 대신 10초 만에 GmailLoginError로 실패
        authorize(
            DESKTOP_CLIENT, should_cancel=cancel.is_set, open_browser=False, timeout_seconds=10
        )


def test_로그인_시간이_지나면_GmailLoginError():
    # given / when / then
    with pytest.raises(GmailLoginError, match="시간"):
        authorize(DESKTOP_CLIENT, timeout_seconds=1, open_browser=False)
