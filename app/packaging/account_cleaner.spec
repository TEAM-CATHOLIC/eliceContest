# PyInstaller 설정. app/ 폴더에서 실행:  uv run pyinstaller packaging/account_cleaner.spec
# 결과: dist/AccountCleaner/ (Windows·Linux), dist/AccountCleaner.app (macOS)
import sys

from PyInstaller.utils.hooks import collect_data_files

APP_NAME = "AccountCleaner"

datas = [
    # 예시 플레이북 등 패키지 안의 데이터 파일(JSON)
    *collect_data_files("account_cleaner"),
    # Playwright 드라이버(node + 패키지). 공식 PyInstaller hook이 없어 직접 넣는다.
    # 브라우저는 넣지 않는다 — 설치된 Chrome(channel="chrome")을 쓴다.
    *collect_data_files("playwright"),
    # Gmail API 디스커버리 문서 (아래에서 gmail.v1만 남긴다)
    *collect_data_files("googleapiclient", includes=["discovery_cache/documents/gmail.v1.json"]),
]

DISCOVERY_DIR = "googleapiclient/discovery_cache/documents/"
KEEP_DISCOVERY = {"gmail.v1.json"}

a = Analysis(
    ["launcher.py"],
    pathex=[],
    datas=datas,
    # providers가 문자열 이름(importlib)으로 불러오는 실제 구현. PyInstaller가 못 찾으므로 직접 넣는다 (#76)
    hiddenimports=["account_cleaner.classifier", "account_cleaner.browser"],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
# googleapiclient용 PyInstaller hook이 디스커버리 문서 전체(약 110MB)를 넣으므로 gmail.v1만 남긴다.
def _keep(dest: str) -> bool:
    dest = dest.replace("\\", "/")  # Windows 경로 구분자
    return not dest.startswith(DISCOVERY_DIR) or dest.rsplit("/", 1)[-1] in KEEP_DISCOVERY


a.datas = [d for d in a.datas if _keep(d[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    argv_emulation=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier="com.team-catholic.accountcleaner",
        info_plist={
            "CFBundleDisplayName": "계정 정리 AI 에이전트",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
