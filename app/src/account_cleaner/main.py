import logging
import sys

from PySide6.QtWidgets import QApplication

from account_cleaner.core.log_setup import setup_logging
from account_cleaner.core.paths import resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.errors import install_excepthook, show_exception
from account_cleaner.ui.main_window import APP_TITLE, MainWindow
from account_cleaner.ui.workers import BackgroundTask

ORGANIZATION = "TEAM-CATHOLIC"
APPLICATION = "AccountCleaner"

log = logging.getLogger(__name__)


def main() -> int:
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
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
