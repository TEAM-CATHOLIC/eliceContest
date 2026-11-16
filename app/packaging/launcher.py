"""PyInstaller 진입점. 패키지 밖에 있어야 상대 import 문제 없이 묶인다."""

import sys

from account_cleaner.main import main

if __name__ == "__main__":
    sys.exit(main())
