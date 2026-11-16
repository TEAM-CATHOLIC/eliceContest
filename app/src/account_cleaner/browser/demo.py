"""로컬 데모: 실제 계정 없이 넘겨주기 → 재개 → 탈퇴 화면 도달(최종 버튼 앞 정지)을 보여 준다.

데모 사이트(`agent/demo_server.py`, 브라우저 담당 작성)를 이 기기 안(127.0.0.1)에 띄우고,
데스크톱과 같은 `PlaywrightWithdrawAgent`로 진행한다. 실제 서비스 화면 변경에 흔들리지 않는 시연용.

    cd app
    uv run python -m account_cleaner.browser.demo

Chrome 창에서 아무 비밀번호나 넣고 로그인한 뒤, 터미널에서 Enter를 누르면 이어서 진행한다.
"""

import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from account_cleaner.browser.agent.demo_server import DemoHandler
from account_cleaner.contracts import AgentEvent, AgentStatus, Playbook

DEMO_PLAYBOOK_ID = "local_demo"


def start_demo_server(port: int = 0) -> ThreadingHTTPServer:
    """데모 사이트를 백그라운드 스레드로 띄운다. `port=0`이면 빈 포트를 고른다."""
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    threading.Thread(target=server.serve_forever, name="demo-site", daemon=True).start()
    return server


def demo_playbook(port: int) -> Playbook:
    base = f"http://127.0.0.1:{port}"
    return Playbook.from_dict(
        {
            "schema_version": 1,
            "id": DEMO_PLAYBOOK_ID,
            "service": "안전 데모",
            "domains": ["127.0.0.1"],
            "login_methods": ["email"],
            "login_url": f"{base}/login",
            "password_reset_url": f"{base}/login",
            "withdraw_url": f"{base}/settings",
            "pre_withdraw_conditions": ["데모 사이트이며 실제 데이터는 삭제되지 않습니다"],
            "steps": [
                {
                    "action": "wait_for",
                    "value": "main",
                    "description": "로그인 후 계정 설정 화면 확인",
                },
                {
                    "action": "reach_target",
                    "value": "text=계정 영구 삭제",
                    "fallback_texts": ["계정 삭제", "Delete account"],
                    "description": "최종 탈퇴 버튼 확인 (클릭 전 정지)",
                },
            ],
        }
    )


def main() -> int:
    from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent

    server = start_demo_server()
    port = server.server_address[1]
    print(f"데모 사이트: http://127.0.0.1:{port}/settings")
    with tempfile.TemporaryDirectory(prefix="account-cleaner-demo-") as profile:
        agent = PlaywrightWithdrawAgent(Path(profile))

        def on_event(event: AgentEvent) -> None:
            step = f"[{event.step.index}/{event.step.total}] " if event.step else ""
            print(f"{event.status.value:>10}  {step}{event.message}")
            if event.status is AgentStatus.USER_TURN:
                # input()은 작업 스레드를 막으면 안 되므로 별도 스레드에서 기다렸다가 resume
                def wait_enter() -> None:
                    input("  → Chrome에서 처리한 뒤 Enter: ")
                    agent.resume()

                threading.Thread(target=wait_enter, daemon=True).start()

        final = agent.run(demo_playbook(port), on_event)
    server.shutdown()
    return 0 if final.status is AgentStatus.REACHED else 1


if __name__ == "__main__":
    raise SystemExit(main())
