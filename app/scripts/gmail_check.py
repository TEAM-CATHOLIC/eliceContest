"""실제 Gmail 계정으로 연결을 확인한다 (개발용). 메일 내용은 출력하지 않고 개수만 보여 준다.

    cd app
    ACCOUNT_CLEANER_GOOGLE_CLIENT_SECRET=~/Downloads/client_secret_....json \\
        uv run python scripts/gmail_check.py --max 200

브라우저에서 테스트 사용자로 등록한 계정으로 로그인하고 "Gmail 메일 보기"를 체크한다.
"""

import argparse
import time
from collections import Counter

from account_cleaner.mail import (
    GmailError,
    GmailMailSource,
    GoogleGmailApi,
    authorize,
    find_client_secret,
    import_mails,
    load_client_config,
    revoke,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=200, help="받을 최대 통수 (기본 200)")
    args = parser.parse_args()

    try:
        config = load_client_config(find_client_secret())
        print("브라우저에서 로그인하세요 (5분 안에)...")
        credentials = authorize(config)
    except GmailError as e:
        print(f"실패: {e}")
        return 1

    try:
        started = time.monotonic()
        source = GmailMailSource(GoogleGmailApi(credentials), max_messages=args.max)
        result = import_mails(
            source, on_progress=lambda d, t: print(f"\r{d}/{t}", end="", flush=True)
        )
    finally:
        revoke(credentials)

    print(f"\n가져온 메일 {len(result.mails)}통, {time.monotonic() - started:.1f}초")
    print(f"중복 {result.stats.duplicates}, 건너뜀 {len(result.stats.skipped)}")
    print(f"발신 도메인 {len({m.sender_domain for m in result.mails})}종")
    print(f"본문이 빈 메일 {sum(1 for m in result.mails if not m.body_text)}통")
    reasons = Counter(s.reason for s in result.stats.skipped)
    for reason, count in reasons.most_common():
        print(f"  건너뜀 이유: {reason} ({count})")
    print("토큰 폐기 완료. 앱 데이터 폴더에는 아무것도 저장하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
