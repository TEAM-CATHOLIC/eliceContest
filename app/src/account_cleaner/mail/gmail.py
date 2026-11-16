"""Gmail 계정 연결 (PRD F-01). OAuth 테스트 모드, 범위는 `gmail.readonly` 하나.

흐름: `authorize()`로 기본 브라우저에서 로그인 → `GmailMailSource`가 메일을 한 통씩 받아 원문으로
바꿔 내보냄 → 공통 정규화(`parse_mail`) → 끝나면 `revoke()`로 토큰 폐기.

- 토큰은 메모리에만 둔다. 파일·설정·로그에 쓰지 않는다 (NF-01).
- 메일은 `format=full`로 받는다. 첨부 본문은 받지 않고(첨부는 `attachmentId`만 옴), 받은 구조를
  MIME 원문으로 다시 조립해 파일 소스와 같은 정규화를 거친다.
"""

import base64
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter, deque
from collections.abc import Callable, Iterator
from email.header import Header
from email.message import Message
from email.utils import formatdate
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

from account_cleaner.contracts import CancelCheck
from account_cleaner.mail.importer import ImportCancelled
from account_cleaner.mail.source import MailSource, RawMail

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRET_ENV = "ACCOUNT_CLEANER_GOOGLE_CLIENT_SECRET"
CLIENT_SECRET_FILE = "google_client_secret.json"
LOGIN_TIMEOUT_SECONDS = 300
INITIAL_BATCH_SIZE = 20
MIN_BATCH_SIZE = 5
MAX_BATCH_SIZE = 50
"""Gmail은 배치 안의 요청을 동시에 처리해 사용자당 동시 요청 한도에 걸리기 쉽다. 20에서 시작해
한도에 걸리면 절반으로 줄이고, 연속으로 성공하면 조금씩 늘린다 (최대 50, Gmail 권장 상한)."""
GROW_AFTER = 3
"""이만큼 연속으로 한도에 안 걸리면 배치를 늘린다."""
GROW_STEP = 5
MAX_ATTEMPTS_PER_MESSAGE = 8
MAX_BACKOFF_SECONDS = 32
MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RATE_LIMIT_REASONS = {"ratelimitexceeded", "userratelimitexceeded"}
"""Gmail은 요청이 몰리면 403에 이 이유를 담아 보낸다 (권한 오류 403과 구분해야 함)."""
MIN_BATCH_INTERVAL = 1.0
"""배치 요청 사이 최소 간격(초). 한도는 사용자당 초당 250단위, 메일 한 통 받기는 5단위 → 초당 50통."""
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
LOGIN_DONE_HTML = "로그인이 끝났습니다. 이 창을 닫고 계정 정리 AI 에이전트로 돌아가세요."


class GmailError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 안내를 담는다."""


class GmailSetupError(GmailError):
    """클라이언트 ID 파일이 없거나 잘못됨 (개발·배포 설정 문제)."""


class GmailLoginError(GmailError):
    """사용자 로그인이 끝나지 않음 (거부, 시간 초과, 권한 체크 해제)."""


# --- 클라이언트 ID 파일 ---


def find_client_secret(app_root: Path | None = None, env: dict | None = None) -> Path:
    """찾는 순서: 환경변수 → 앱 데이터 폴더 → 실행파일에 포함된 파일(배포 빌드)."""
    env = os.environ if env is None else env
    candidates = []
    if value := env.get(CLIENT_SECRET_ENV, "").strip():
        candidates.append(Path(value).expanduser())
    if app_root is not None:
        candidates.append(app_root / CLIENT_SECRET_FILE)
    bundled = resources.files("account_cleaner") / "resources" / CLIENT_SECRET_FILE
    candidates.append(Path(str(bundled)))
    for path in candidates:
        if path.is_file():
            return path
    raise GmailSetupError(
        "Gmail 연결 설정 파일(클라이언트 ID)을 찾지 못했습니다.\n"
        f"앱 데이터 폴더에 {CLIENT_SECRET_FILE}을 두거나 {CLIENT_SECRET_ENV}로 경로를 지정하세요."
    )


def load_client_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise GmailSetupError(f"클라이언트 ID 파일을 읽지 못했습니다: {path.name}") from e
    if "installed" not in config:
        kind = next(iter(config), "알 수 없음")
        raise GmailSetupError(
            f"클라이언트 유형이 '{kind}'입니다. Google Cloud에서 '데스크톱 앱' 유형으로 만드세요."
        )
    return config


# --- 로그인 ---


def _cancel_watcher(flow: Any, should_cancel: CancelCheck, done: threading.Event) -> None:
    """로그인을 기다리는 동안 취소 요청이 오면 로컬 리디렉션 주소를 직접 불러 대기를 끝낸다.

    `localhost` 대신 `127.0.0.1`로 부른다. 라이브러리가 가로채기 방지를 위해 IPv6 `::1`을 잡아만
    두는데, macOS는 `localhost`를 `::1`로 먼저 찾아 요청이 서버에 닿지 않는다.
    대기가 끝날 때까지(서버가 요청을 받을 때까지) 반복한다.
    """
    while not done.wait(0.2):
        if not should_cancel():
            continue
        uri = getattr(flow, "redirect_uri", None)
        if not uri:
            continue
        port = urllib.parse.urlsplit(uri).port
        try:
            url = f"http://127.0.0.1:{port}/?error=access_denied"
            urllib.request.urlopen(url, timeout=2).close()
        except OSError:
            pass


def authorize(
    client_config: dict,
    should_cancel: CancelCheck | None = None,
    timeout_seconds: int = LOGIN_TIMEOUT_SECONDS,
    open_browser: bool = True,
) -> Any:
    """기본 브라우저로 구글 로그인 창을 열고, 허락하면 자격 증명(메모리)을 돌려준다.

    작업 스레드에서 부른다 (로그인이 끝날 때까지 블로킹). 취소하면 `ImportCancelled`.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
    from oauthlib.oauth2.rfc6749.errors import OAuth2Error

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    done = threading.Event()
    if should_cancel:
        args = (flow, should_cancel, done)
        threading.Thread(target=_cancel_watcher, args=args, daemon=True).start()
    try:
        credentials = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            authorization_prompt_message="",  # 창 모드 실행파일에는 stdout이 없다
            success_message=LOGIN_DONE_HTML,
            timeout_seconds=timeout_seconds,
        )
    except WSGITimeoutError as e:
        raise GmailLoginError("로그인 시간이 지났습니다. 다시 시도해 주세요.") from e
    except OAuth2Error as e:
        if should_cancel and should_cancel():
            raise ImportCancelled from e
        raise GmailLoginError("구글 로그인을 취소했거나 허락하지 않았습니다.") from e
    except Warning as e:  # oauthlib: 받은 권한이 요청과 다름
        raise GmailLoginError(
            "Gmail 메일 보기 권한이 체크되지 않았습니다. 다시 로그인해 체크해 주세요."
        ) from e
    finally:
        done.set()
    if not credentials.has_scopes(SCOPES):
        raise GmailLoginError(
            "Gmail 메일 보기 권한이 체크되지 않았습니다. 다시 로그인해 체크해 주세요."
        )
    return credentials


def revoke(credentials: Any) -> None:
    """토큰을 구글에서도 폐기한다 (가져오기가 끝나면 앱이 메일함에 다시 접근할 수 없게). 실패해도 무시."""
    token = getattr(credentials, "token", None)
    if not token:
        return
    data = urllib.parse.urlencode({"token": token}).encode()
    try:
        urllib.request.urlopen(REVOKE_URL, data=data, timeout=5).close()
    except OSError:
        log.warning("Gmail 토큰 폐기 요청 실패 (1시간 뒤 자동 만료)")


# --- Gmail API ---


class GmailApi(Protocol):
    """필요한 Gmail API 호출만. 테스트에서는 가짜로 바꿔 끼운다."""

    def profile_email(self) -> str: ...

    def list_ids(self, page_token: str | None, query: str | None) -> tuple[list[str], str | None]:
        """(메시지 ID 목록, 다음 페이지 토큰)"""
        ...

    def get_full(self, ids: list[str]) -> dict[str, dict | Exception]:
        """ID별 `format=full` 응답, 실패한 것은 예외."""
        ...


def http_status(error: Exception | None) -> int | None:
    resp = getattr(error, "resp", None)
    status = getattr(resp, "status", None)
    return int(status) if status is not None else None


def error_reasons(error: Exception | None) -> set[str]:
    """Gmail 오류 응답 본문의 `error.errors[].reason` (소문자)."""
    content = getattr(error, "content", b"") or b""
    try:
        body = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    except (ValueError, UnicodeDecodeError):
        return set()
    details = body.get("error", {}) if isinstance(body, dict) else {}
    return {
        str(e.get("reason", "")).lower() for e in details.get("errors", []) if isinstance(e, dict)
    }


def is_retryable(error: Exception | None) -> bool:
    """잠시 뒤 다시 하면 될 오류인가 (요청 한도 초과·서버 오류). 응답이 아예 없어도 다시 한다."""
    if error is None:
        return True
    status = http_status(error)
    if status in RETRYABLE_STATUS:
        return True
    return status == 403 and bool(error_reasons(error) & RATE_LIMIT_REASONS)


class GoogleGmailApi:
    """`google-api-python-client`로 구현. 디스커버리 문서는 패키지에 포함된 것을 쓴다 (네트워크 없음)."""

    def __init__(self, credentials: Any = None, http: Any = None) -> None:
        """`http`는 테스트용 (가짜 HTTP 응답). 실제로는 `credentials`만 넘긴다."""
        from googleapiclient.discovery import build

        auth = {"http": http} if http is not None else {"credentials": credentials}
        self._service = build("gmail", "v1", static_discovery=True, cache_discovery=False, **auth)
        self._messages = self._service.users().messages()

    def profile_email(self) -> str:
        profile = self._service.users().getProfile(userId="me").execute(num_retries=MAX_RETRIES)
        return profile.get("emailAddress", "")

    def list_ids(self, page_token: str | None, query: str | None) -> tuple[list[str], str | None]:
        response = self._messages.list(
            userId="me", maxResults=500, pageToken=page_token, q=query or None
        ).execute(num_retries=MAX_RETRIES)
        return [m["id"] for m in response.get("messages", [])], response.get("nextPageToken")

    def get_full(self, ids: list[str]) -> dict[str, dict | Exception]:
        results: dict[str, dict | Exception] = {}

        def callback(request_id: str, response: dict, exception: Exception | None) -> None:
            results[request_id] = exception if exception is not None else response

        batch = self._service.new_batch_http_request(callback=callback)
        for message_id in ids:
            request = self._messages.get(userId="me", id=message_id, format="full")
            batch.add(request, request_id=message_id)  # 두 번째 위치 인자는 callback이다
        batch.execute()
        return results


# --- format=full → MIME 원문 ---


def _decode_body(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _build_part(part: dict) -> Message:
    msg = Message()
    for header in part.get("headers", []):
        name, value = header.get("name", ""), header.get("value", "")
        if not name or name.lower() == "content-transfer-encoding":
            continue
        msg[name] = value if value.isascii() else Header(value, "utf-8").encode()
    mime = part.get("mimeType", "")
    if mime.startswith("multipart/") and part.get("parts"):
        if msg.get("Content-Type") is None:
            msg["Content-Type"] = mime
        msg.set_payload([_build_part(child) for child in part["parts"]])
        return msg
    # 본문이 있는 파트만 데이터가 온다. 첨부는 attachmentId만 오므로 빈 본문이 된다.
    data = part.get("body", {}).get("data", "")
    raw = _decode_body(data) if data else b""
    msg["Content-Transfer-Encoding"] = "base64"
    msg.set_payload(base64.encodebytes(raw).decode("ascii"))
    return msg


def message_to_bytes(message: dict) -> bytes:
    """Gmail API `format=full` 응답을 MIME 원문 바이트로. Date가 없으면 Gmail 수신 시각을 넣는다."""
    msg = _build_part(message.get("payload", {}))
    if msg.get("Date") is None and message.get("internalDate"):
        msg["Date"] = formatdate(int(message["internalDate"]) / 1000, usegmt=True)
    return msg.as_bytes()


# --- 메일 소스 ---


class GmailMailSource(MailSource):
    """연결한 Gmail 메일함 전체(스팸·휴지통 제외). 진행률 단위는 통 수."""

    def __init__(
        self,
        api: GmailApi,
        query: str | None = None,
        max_messages: int | None = None,
        should_cancel: CancelCheck | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api = api
        self._query = query
        self._max = max_messages
        self._should_cancel = should_cancel or (lambda: False)
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.batch_size = INITIAL_BATCH_SIZE
        self.rate_limited = 0
        """한도에 걸려 다시 보낸 횟수 (속도 조정 확인용)"""
        self._ids: list[str] | None = None
        self._failures: list[tuple[str, str]] = []
        self.account = ""

    @property
    def name(self) -> str:
        return f"Gmail ({self.account})" if self.account else "Gmail"

    def _check_cancel(self) -> None:
        if self._should_cancel():
            raise ImportCancelled

    def message_ids(self) -> list[str]:
        """전체 메시지 ID 목록 (처음 한 번만 받는다)."""
        if self._ids is None:
            self.account = self.account or self._api.profile_email()
            ids: list[str] = []
            token = None
            while True:
                self._check_cancel()
                page, token = self._api.list_ids(token, self._query)
                ids.extend(page)
                if not token or (self._max and len(ids) >= self._max):
                    break
            self._ids = ids[: self._max] if self._max else ids
        return self._ids

    def total(self) -> int:
        return len(self.message_ids())

    def failures(self) -> list[tuple[str, str]]:
        return list(self._failures)

    def _get_full_paced(self, ids: list[str]) -> dict[str, dict | Exception]:
        """배치 요청 사이에 `MIN_BATCH_INTERVAL`을 둔다 (요청이 몰려 한도에 걸리지 않게)."""
        if self._last_request is not None:
            wait = MIN_BATCH_INTERVAL - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()
        return self._api.get_full(ids)

    def __iter__(self) -> Iterator[RawMail]:
        """대기열에서 배치 크기만큼 꺼내 받는다. 한도에 걸린 메일은 대기열 앞으로 돌려보낸다."""
        queue = deque(self.message_ids())
        attempts: Counter[str] = Counter()
        done = clean_streak = backoff_level = 0
        while queue:
            self._check_cancel()
            chunk = [queue.popleft() for _ in range(min(self.batch_size, len(queue)))]
            results = self._get_full_paced(chunk)
            limited = []
            for message_id in chunk:
                result = results.get(message_id)
                origin = f"gmail:{message_id}"
                if isinstance(result, dict):
                    done += 1
                    yield RawMail(message_to_bytes(result), origin, done)
                elif not is_retryable(result):
                    done += 1
                    self._failures.append((origin, f"받기 실패 ({http_status(result)})"))
                else:
                    attempts[message_id] += 1
                    self.rate_limited += 1
                    if attempts[message_id] < MAX_ATTEMPTS_PER_MESSAGE:
                        limited.append(message_id)
                        continue
                    done += 1
                    self._failures.append((origin, "요청 한도 초과로 받지 못함"))
            if limited:
                queue.extendleft(reversed(limited))
                self.batch_size = max(MIN_BATCH_SIZE, self.batch_size // 2)
                clean_streak = 0
                self._sleep(min(2**backoff_level, MAX_BACKOFF_SECONDS))
                backoff_level += 1
            else:
                backoff_level = 0
                clean_streak += 1
                if clean_streak >= GROW_AFTER:
                    self.batch_size = min(MAX_BATCH_SIZE, self.batch_size + GROW_STEP)
                    clean_streak = 0
