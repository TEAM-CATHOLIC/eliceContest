"""디자인 작업용: 가짜 메일·가짜 진행 기록으로 앱을 띄운다 (개발용).

실제 메일, 실제 앱 데이터 폴더, OS 키체인, 실제 사이트는 건드리지 않는다.
- 데이터 폴더: 실행할 때마다 새 임시 폴더 (끝나면 지움)
- 암호화 키: 그 임시 폴더 안 키 파일 (키체인 안 씀)
- 분석기·에이전트·플레이북: 전부 가짜 (`ACCOUNT_CLEANER_FAKE=all`)

    cd app
    uv run python scripts/design_preview.py            # 메일 불러온 상태 + 진행 기록
    uv run python scripts/design_preview.py --empty    # 처음 켠 상태 (빈 화면 디자인 확인용)

pyside6-mcp로 띄울 때: launch_app(cwd=<app 폴더 절대경로>, script="scripts/design_preview.py")
"""

import argparse
import mailbox
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

USER = "me@example.com"

# (도메인, 보낸 사람 이름, [(며칠 전, 제목, 본문)])
SERVICES: list[tuple[str, str, list[tuple[int, str, str]]]] = [
    (
        "github.com",
        "GitHub",
        [
            (
                2400,
                "[GitHub] 가입을 환영합니다",
                "GitHub 계정이 만들어졌습니다. 이메일 인증을 마쳐 주세요.",
            ),
            (900, "[GitHub] 새로운 기기에서 로그인 알림", "Chrome on Windows에서 로그인했습니다."),
            (30, "[GitHub] Your weekly digest", "이번 주 저장소 소식입니다."),
        ],
    ),
    (
        "dropbox.com",
        "Dropbox",
        [
            (1800, "Dropbox에 오신 것을 환영합니다", "Dropbox 가입이 완료되었습니다."),
            (400, "Dropbox 비밀번호가 변경되었습니다", "본인이 아니라면 바로 알려 주세요."),
        ],
    ),
    (
        "linkedin.com",
        "LinkedIn",
        [
            (2100, "LinkedIn 가입 환영 메일", "프로필을 완성해 보세요."),
            (60, "회원님을 위한 새 채용 공고", "관심 있을 만한 공고 5개"),
        ],
    ),
    (
        "notion.so",
        "Notion",
        [
            (700, "Welcome to Notion", "워크스페이스를 만들어 보세요."),
            (20, "Notion 로그인 알림", "새로운 기기에서 로그인했습니다."),
        ],
    ),
    (
        "spotify.com",
        "Spotify",
        [
            (1500, "Spotify 가입을 환영합니다", "지금 음악을 들어 보세요."),
            (45, "Spotify Premium 결제 영수증", "결제가 완료되었습니다. 10,900원"),
        ],
    ),
    (
        "coupang.com",
        "쿠팡",
        [
            (1300, "쿠팡 회원 가입을 축하드립니다", "첫 구매 쿠폰이 도착했어요."),
            (10, "주문하신 상품이 배송 출발했습니다", "주문번호 1234-5678"),
            (9, "배송 완료 안내", "상품이 문 앞에 도착했습니다."),
        ],
    ),
    (
        "figma.com",
        "Figma",
        [
            (600, "Figma 이메일 인증", "이메일 주소를 인증해 주세요."),
        ],
    ),
    (
        "duolingo.com",
        "Duolingo",
        [
            (1100, "Duolingo에 오신 걸 환영해요", "오늘의 학습을 시작해 보세요."),
            (5, "연속 학습이 끊기기 직전이에요!", "지금 1분만 공부해요."),
        ],
    ),
    (
        "yanolja.com",
        "야놀자",
        [
            (2600, "야놀자 회원가입 완료", "가입 축하 쿠폰을 드려요."),
            (
                800,
                "장기 미이용 휴면 전환 예정 안내",
                "1년간 로그인하지 않아 휴면 계정으로 전환됩니다.",
            ),
        ],
    ),
    (
        "canva.com",
        "Canva",
        [
            (300, "Canva 약관 변경 안내", "서비스 약관이 바뀝니다."),
        ],
    ),
    (
        "medium.com",
        "Medium",
        [
            (1000, "Medium Daily Digest", "오늘의 추천 글"),
        ],
    ),
    (
        "oldshop.co.kr",
        "올드샵",
        [
            (3000, "올드샵 회원가입 감사합니다", "가입이 완료되었습니다."),
            (200, "회원 탈퇴 완료 안내", "그동안 이용해 주셔서 감사합니다."),
        ],
    ),
]


def write_mbox(path: Path, now: datetime) -> None:
    box = mailbox.mbox(path)
    for domain, name, mails in SERVICES:
        for n, (days, subject, body) in enumerate(mails):
            msg = EmailMessage()
            msg["From"] = f"{name} <no-reply@{domain}>"
            msg["To"] = USER
            msg["Subject"] = subject
            msg["Date"] = format_datetime(now - timedelta(days=days))
            msg["Message-ID"] = f"<preview-{domain}-{n}@example.com>"
            msg.set_content(f"{body}\n\n이 메일은 디자인 미리보기용 가짜 메일입니다.")
            box.add(msg)
    box.flush()
    box.close()


def seed_history(db_path: Path, now: datetime) -> None:
    """진행 기록 화면이 비지 않도록 상태와 기록을 과거 시각으로 넣는다."""
    from account_cleaner.storage import Database, StatusStore

    clock = {"now": now}
    db = Database(db_path, clock=lambda: clock["now"])
    store = StatusStore(db)

    def at(days_ago: float) -> None:
        clock["now"] = now - timedelta(days=days_ago)

    # GitHub: 탈퇴 화면까지 갔지만 안 끝냄 → 14일 지나 재알림 대상
    at(16)
    store.set_label("github.com", "GitHub", "confirmed")
    store.agent_started("github.com", "GitHub")
    at(15.99)
    store.agent_finished("github.com", "reached", reached=True)
    # LinkedIn: 완료
    at(5)
    store.set_label("linkedin.com", "LinkedIn", "confirmed")
    store.agent_started("linkedin.com", "LinkedIn")
    at(4.99)
    store.agent_finished("linkedin.com", "reached", reached=True)
    at(4.9)
    store.mark_completed("linkedin.com")
    # Dropbox: 지금 안내 중 (로그인 기다리다 중단)
    at(0.2)
    store.agent_started("dropbox.com", "Dropbox")
    store.agent_finished("dropbox.com", "stopped", reached=False)
    # 나머지 라벨
    at(1)
    store.set_label("notion.so", "Notion", "confirmed")
    store.set_label("medium.com", "Medium", "excluded")
    store.set_label("spotify.com", "Spotify", "deferred")
    db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--empty", action="store_true", help="메일·기록 없이 처음 켠 상태")
    args, rest = parser.parse_known_args()

    root = Path(tempfile.mkdtemp(prefix="account-cleaner-preview-"))
    os.environ["ACCOUNT_CLEANER_HOME"] = str(root)
    os.environ["ACCOUNT_CLEANER_KEY_STORE"] = "file"
    os.environ["ACCOUNT_CLEANER_FAKE"] = "all"
    print(f"[design-preview] 임시 데이터 폴더: {root}", file=sys.stderr)

    from account_cleaner import main as app_main
    from account_cleaner.core.paths import resolve_app_paths

    argv = [sys.argv[0], *rest]
    if not args.empty:
        now = datetime.now(UTC)
        mbox = root / "preview.mbox"
        write_mbox(mbox, now)
        seed_history(resolve_app_paths().database, now)
        argv += ["--import-file", str(mbox)]
    sys.argv = argv
    try:
        return app_main.main()
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
