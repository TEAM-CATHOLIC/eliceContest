"""Synthetic one-service demo mailbox and website, isolated from all real accounts."""

import secrets
import threading
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from account_cleaner.browser.demo import demo_playbook

DOMAIN = "127.0.0.1"
SERVICE = "모아북 (시연)"


class DemoSession:
    def __init__(self, root: Path):
        self.token = secrets.token_urlsafe(24)
        self.root = root / secrets.token_hex(8)
        self.root.mkdir(parents=True)
        self.usage_path = self.root / "usage.eml"
        self.completion_path = self.root / "completion.eml"
        self.started_at: datetime | None = None
        self.reached = False
        self._lock = threading.Lock()
        self._write_mail(
            self.usage_path,
            "usage",
            "[시연용 모아북] 회원가입 완료 안내",
            "시연용으로 생성한 메일입니다. 실제 가입 기록이 아닙니다.\n"
            "모아북 회원가입이 완료되었습니다. 가입해 주셔서 감사합니다.",
            datetime.now(UTC) - timedelta(days=30),
        )

    def _write_mail(self, path, kind, subject, body, date):
        mail = EmailMessage()
        mail["From"] = f"no-reply@{DOMAIN}"
        mail["To"] = "demo@example.invalid"
        mail["Message-ID"] = f"<demo-{self.root.name}-{kind}@{DOMAIN}>"
        mail["Date"] = format_datetime(date)
        mail["Subject"] = subject
        mail["X-Account-Cleaner-Synthetic"] = "true"
        mail.set_content(body)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(mail.as_bytes())
        temp.replace(path)

    def start(self):
        if self.started_at is None:
            self.started_at = datetime.now(UTC)

    def complete_by_user(self):
        with self._lock:
            if self.started_at is None or not self.reached:
                raise ValueError("탈퇴 화면 안내 전에는 완료 메일을 생성할 수 없습니다")
            if not self.completion_path.exists():
                self._write_mail(
                    self.completion_path,
                    "completed",
                    "[시연용 모아북] 회원 탈퇴 완료 안내",
                    "시연용으로 생성한 메일입니다. 실제 계정이나 데이터는 삭제되지 않았습니다.\n"
                    "모아북 회원 탈퇴 처리가 완료되었습니다. 계정이 삭제되었습니다.",
                    datetime.now(UTC),
                )
        return self.completion_path


def start_site(session: DemoSession):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def host_ok(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def page(self, body, refresh=False):
            content = (
                "<!doctype html><html lang='ko'><meta charset='utf-8'><title>모아북 시연</title>"
                + ("<meta http-equiv='refresh' content='1;url=/settings'>" if refresh else "")
                + "<style>body{font:17px/1.8 system-ui;background:#f1f5ef;color:#204235}"
                "main{max-width:700px;margin:55px auto;padding:35px;background:white;border-radius:15px}"
                "button{font:inherit;padding:12px 22px;background:#176b50;color:white;border:0;"
                "border-radius:7px;cursor:pointer}.tag{color:#b16416;font-weight:bold}</style>"
                "<main><div class='tag'>시연용 가상 서비스 · 실제 계정 삭제 없음</div>"
                + body
                + "</main></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(content)

        def authenticated(self):
            return f"demo_session={session.token}" in self.headers.get("Cookie", "").split("; ")

        def redirect(self, url, cookie=False):
            self.send_response(303)
            self.send_header("Location", url)
            if cookie:
                self.send_header(
                    "Set-Cookie", f"demo_session={session.token}; HttpOnly; SameSite=Strict; Path=/"
                )
            self.end_headers()

        def do_GET(self):
            if not self.host_ok():
                return self.send_error(403)
            if self.path == "/login":
                return self.page(
                    "<h1>모아북 시연 계정</h1><p>실제 비밀번호는 입력하지 않습니다.</p>"
                    "<label>시연 인증 표시 (입력 불필요) "
                    "<input type='password' value='demo' readonly aria-label='시연 인증 표시'></label>"
                    "<form method='post' action='/login'><button>시연 계정으로 계속</button></form>"
                )
            if self.path == "/settings":
                if not self.authenticated():
                    return self.redirect("/login")
                ready = session.reached
                return self.page(
                    "<h1>모아북 계정 설정</h1>"
                    + (
                        "<p>에이전트 도착 확인 완료. 이제 시연 버튼을 직접 누를 수 있습니다.</p>"
                        if ready
                        else "<p>에이전트가 도착을 확인 중입니다. 잠시 기다리면 버튼이 활성화됩니다.</p>"
                    )
                    + "<p>사용자가 누르면 로컬 시연용 탈퇴 완료 메일 1통을 생성합니다. "
                    "실제 계정과 데이터에는 아무 변화가 없습니다.</p>"
                    "<form method='post' action='/complete'>"
                    f"<input type='hidden' name='token' value='{session.token}'>"
                    f"<button {'disabled' if not ready else ''}>계정 영구 삭제 (시연용 메일 생성)</button></form>",
                    refresh=not ready,
                )
            if self.path == "/done" and self.authenticated():
                return self.page(
                    "<h1>시연용 완료 메일을 만들었습니다</h1>"
                    "<p>앱이 새 메일을 읽고 완료 근거를 확인하면 알림을 표시합니다.</p>"
                    "<p>실제 계정이나 데이터를 삭제한 것은 아닙니다.</p>"
                )
            self.send_error(404)

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self.host_ok() or self.headers.get("Origin") != origin:
                return self.send_error(403)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 4096:
                return self.send_error(400)
            data = parse_qs(self.rfile.read(size).decode())
            if self.path == "/login":
                return self.redirect("/settings", cookie=True)
            if (
                self.path == "/complete"
                and self.authenticated()
                and data.get("token") == [session.token]
            ):
                try:
                    session.complete_by_user()
                except ValueError:
                    return self.redirect("/settings")
                return self.redirect("/done")
            self.send_error(403)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="mail-demo-site").start()
    return server, demo_playbook(server.server_port)
