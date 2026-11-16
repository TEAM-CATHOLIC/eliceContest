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
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pydoc", "pytest"],
    noarchive=False,
)
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
