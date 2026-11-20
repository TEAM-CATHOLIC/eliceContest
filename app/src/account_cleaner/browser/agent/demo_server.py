from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STYLE = """
body{font-family:system-ui,sans-serif;background:#f4f7fb;margin:0;color:#172b4d}
main{max-width:720px;margin:64px auto;background:#fff;padding:40px;border-radius:18px;box-shadow:0 12px 40px #172b4d22}
label{display:block;margin:20px 0 8px}input{width:100%;padding:12px;box-sizing:border-box}
button{margin-top:20px;padding:12px 18px;border:0;border-radius:8px;background:#2457d6;color:#fff;font-weight:700}
.danger{border-top:1px solid #dde3ec;margin-top:36px;padding-top:28px}.danger button{background:#b42318}
.tag{color:#2457d6;font-weight:700}
"""


def page(body: str) -> bytes:
    return f"<!doctype html><html lang='ko'><meta charset='utf-8'><title>계정 정리 데모</title><style>{STYLE}</style><body>{body}</body></html>".encode()


class DemoHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, *headers: tuple[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/generic":
            self._send(
                200,
                page("""
                <main><div class='tag'>GENERIC AGENT DEMO</div><h1>내 서비스</h1>
                <p>홍길동 hong@example.com 계정으로 로그인했습니다.</p>
                <a href='/generic/account'>홍길동 계정 설정</a></main>
            """),
            )
            return
        if self.path == "/generic/account":
            self._send(
                200,
                page("""
                <main><div class='tag'>GENERIC ACCOUNT SETTINGS</div><h1>계정 설정</h1>
                <section class='danger'><h2>계정 삭제</h2>
                <button>계정 영구 삭제</button></section></main>
            """),
            )
            return
        if self.path == "/login":
            self._send(
                200,
                page("""
                <main><div class='tag'>SAFE HANDOFF DEMO</div><h1>사용자 인증</h1>
                <p>에이전트는 비밀번호를 입력하지 않습니다. 사용자가 직접 입력한 뒤 계속합니다.</p>
                <form method='post' action='/login'><label for='password'>데모 비밀번호</label>
                <input id='password' name='password' type='password' autocomplete='current-password' required>
                <button type='submit'>사용자가 직접 로그인</button></form></main>
            """),
            )
            return
        if self.path == "/settings":
            if "demo_session=1" not in self.headers.get("Cookie", ""):
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            self._send(
                200,
                page("""
                <main><div class='tag'>ACCOUNT SETTINGS</div><h1>계정 설정</h1>
                <p>로그인 세션이 확인되었습니다.</p><section class='danger'><h2>계정 삭제</h2>
                <p>이 버튼은 데모용이며 실제 데이터는 삭제하지 않습니다. 에이전트는 버튼을 발견하면 클릭하지 않고 멈춥니다.</p>
                <button disabled>계정 영구 삭제</button></section></main>
            """),
            )
            return
        self.send_response(302)
        self.send_header("Location", "/settings")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/login":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(303)
        self.send_header("Set-Cookie", "demo_session=1; HttpOnly; SameSite=Strict")
        self.send_header("Location", "/settings")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def serve(port: int) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    print(f"demo site: http://127.0.0.1:{port}/settings", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="브라우저 에이전트 해커톤 로컬 데모")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(args.port)


if __name__ == "__main__":
    main()
