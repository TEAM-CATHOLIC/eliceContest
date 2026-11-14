import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from account_cleaner.core.chrome import CHROME_DOWNLOAD_URL, find_chrome
from account_cleaner.core.log_setup import setup_logging
from account_cleaner.core.paths import resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.errors import install_excepthook, show_exception
from account_cleaner.ui.main_window import APP_TITLE, MainWindow
from account_cleaner.ui.workers import BackgroundTask

ORGANIZATION = "TEAM-CATHOLIC"
APPLICATION = "AccountCleaner"

log = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="account-cleaner")
    parser.add_argument(
        "--self-test", action="store_true", help="창 없이 묶인 구성요소를 확인하고 종료"
    )
    parser.add_argument("--require-chrome", action="store_true", help="Chrome이 없으면 실패")
    parser.add_argument("--report", type=Path, help="self-test 결과를 쓸 파일")
    # macOS가 붙이는 -psn_* 같은 인자와 Qt 인자는 무시한다.
    args, _ = parser.parse_known_args(argv)
    return args


def self_test(args: argparse.Namespace) -> int:
    from account_cleaner.core.self_test import run_self_test

    checks = run_self_test(require_chrome=args.require_chrome)
    text = "\n".join(c.line() for c in checks) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    if sys.stdout is not None:  # 창 모드 실행파일(Windows)에는 stdout이 없다
        sys.stdout.write(text)
    return 0 if all(c.ok for c in checks) else 1


def warn_if_chrome_missing(parent: QWidget) -> None:
    if find_chrome() is not None:
        return
    log.warning("Chrome을 찾지 못함")
    QMessageBox.warning(
        parent,
        "Chrome이 필요합니다",
        "탈퇴 화면 안내는 Google Chrome으로 진행합니다.\n"
        f"Chrome을 설치한 뒤 앱을 다시 실행해 주세요.\n\n{CHROME_DOWNLOAD_URL}",
    )


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.self_test:
        return self_test(args)

    app = QApplication(sys.argv)
    app.setOrganizationName(ORGANIZATION)
    app.setApplicationName(APPLICATION)
    app.setApplicationDisplayName(APP_TITLE)

    try:
        paths = resolve_app_paths()
    except (OSError, RuntimeError) as e:
        show_exception(None, e, "앱 데이터 폴더를 만들 수 없습니다.")
        return 1

    setup_logging(paths.logs)
    install_excepthook()
    log.info("앱 시작 (데이터 폴더: %s)", paths.root)

    window = MainWindow(AppSettings(paths.settings_file))
    app.aboutToQuit.connect(BackgroundTask.shutdown_all)
    window.show()
    QTimer.singleShot(0, lambda: warn_if_chrome_missing(window))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
