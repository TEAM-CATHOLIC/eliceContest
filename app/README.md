# 계정 정리 AI 에이전트 — 데스크톱 앱

Python 3.12 + PySide6 + Playwright로 만드는 Mac/Windows 데스크톱 앱이다.
무엇을 왜 만드는지는 [`../docs`](../docs)를 먼저 읽는다 (PRD → ADR → 논의사항 순).

---

## 1. 처음 세팅하기

Python은 따로 설치하지 않아도 된다. **uv가 Python 3.12를 알아서 내려받아** 이 프로젝트 전용으로 쓴다.
이미 다른 버전의 Python이 깔려 있어도 상관없다.

### 1-1. 준비물 설치 (PC당 한 번)

| 준비물 | 용도 | 확인 명령 |
|---|---|---|
| Git | 코드 받기 | `git --version` |
| uv | Python 버전·라이브러리 관리 | `uv --version` |
| Google Chrome | 브라우저 에이전트가 이 Chrome을 빌려 씀 (PoC는 Chrome만 지원) | Chrome이 실행되면 OK |

**uv 설치**

macOS (터미널):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# 또는 Homebrew를 쓴다면: brew install uv
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# 또는: winget install --id=astral-sh.uv -e
```

설치 후 **터미널을 닫았다 다시 열고** `uv --version`이 나오는지 확인한다.

### 1-2. 코드 받고 환경 만들기

```bash
git clone https://github.com/TEAM-CATHOLIC/eliceContest.git
cd eliceContest/app
uv sync
```

`uv sync`가 하는 일:

1. Python 3.12가 없으면 내려받는다 (`.python-version` 파일 기준)
2. `app/.venv` 가상환경을 만든다
3. `uv.lock`에 적힌 **정확히 같은 버전**의 라이브러리를 설치한다 (앱 + 개발 도구)

### 1-3. AI 작업을 하는 사람만 (선택)

메일 분류기(임베딩 + 로지스틱 회귀)를 다룰 사람은 ml 그룹을 추가로 설치한다.
torch가 함께 깔려서 수 GB가 필요하고 시간이 걸린다.

```bash
uv sync --group ml
```

> ⚠️ 이후 그냥 `uv sync`를 실행하면 ml 라이브러리가 다시 지워진다. AI 작업자는 계속 `uv sync --group ml`을 쓴다.

### 1-4. 잘 됐는지 확인

```bash
uv run pytest            # 테스트 2개 통과하면 OK (앱 창 생성, Chrome 실행)
uv run account-cleaner   # "환경 세팅 완료" 창이 뜨면 OK
```

---

## 2. 에디터 설정

### VS Code

1. `eliceContest/app` 폴더를 연다 (또는 저장소 루트를 열어도 된다)
2. `Ctrl/Cmd + Shift + P` → **Python: Select Interpreter**
3. `app/.venv` 안의 Python 3.12를 고른다
   - macOS: `app/.venv/bin/python`
   - Windows: `app\.venv\Scripts\python.exe`
4. 추천 확장: **Python**, **Ruff**

### PyCharm

Settings → Project → Python Interpreter → Add Interpreter → **Existing** → 위 경로의 python 선택.

---

## 3. 평소에 쓰는 명령

모두 `app/` 폴더에서 실행한다. `uv run`을 앞에 붙이면 가상환경을 켜지 않아도 된다.

| 하고 싶은 것 | 명령 |
|---|---|
| 앱 실행 | `uv run account-cleaner` |
| 테스트 | `uv run pytest` |
| 린트 검사 | `uv run ruff check .` |
| 코드 자동 정리 | `uv run ruff format .` |
| 다른 사람이 라이브러리를 추가한 뒤 pull 받았을 때 | `uv sync` |

## 4. 라이브러리 추가·삭제

**`pip install`은 쓰지 않는다.** 내 PC에만 깔리고 팀원에게 공유되지 않는다.

```bash
uv add 패키지이름            # 앱에 필요한 라이브러리
uv add --dev 패키지이름      # 테스트·빌드 등 개발용
uv add --group ml 패키지이름 # AI 작업용
uv remove 패키지이름         # 삭제
```

명령을 실행하면 `pyproject.toml`과 `uv.lock`이 바뀐다. **두 파일을 같이 커밋**해야 팀원들이 `uv sync`로 똑같이 받는다.

---

## 5. 폴더 구조

```
app/
├── pyproject.toml      ← 프로젝트 정보, 라이브러리 목록
├── uv.lock             ← 라이브러리 정확한 버전 (직접 수정 금지)
├── .python-version     ← 3.12
├── src/account_cleaner/
│   ├── main.py         ← 진입점
│   ├── ui/             ← PySide6 화면
│   ├── browser/        ← Playwright, 플레이북, 넘겨주기
│   ├── mail/           ← MBOX/EML 파싱
│   ├── classifier/     ← 임베딩 + 로지스틱 회귀
│   └── storage/        ← SQLite
└── tests/
```

## 6. 꼭 지킬 것

- **실제 메일 파일(`.mbox`, `.eml`)과 SQLite 파일은 커밋하지 않는다.** `.gitignore`에 걸려 있지만, 테스트용 메일은 `app/data/` 아래에 두면 안전하다.
- 브라우저 테스트는 **본인 계정으로 최종 탈퇴 버튼을 누르지 않는다** (PRD 5장).
- **테스트 함수 이름은 한글로, 무엇을 보장하는지 문장으로 쓴다.** `test_` 접두사는 pytest가 찾기 위해 남긴다. 본문은 `# given`, `# when`, `# then` 주석으로 나눈다. 준비가 따로 없거나 실행과 확인이 붙어 있으면 `# given / when`, `# when / then`처럼 합친다.

```python
def test_비밀번호나_토큰_설정키는_저장을_거부한다(tmp_path):
    # given
    settings = AppSettings(tmp_path / "settings.ini")

    # when / then
    with pytest.raises(ValueError):
        settings.set("naver/password", "x")
```

---

## 7. 문제 해결

| 증상 | 해결 |
|---|---|
| `uv: command not found` / `'uv'은(는) ... 인식되지 않습니다` | 터미널을 다시 연다. 그래도 안 되면 uv 설치 명령을 다시 실행한다 |
| Windows에서 스크립트 실행이 막힘 | PowerShell 대신 명령 앞에 `uv run`을 붙여 실행한다 (가상환경 activate 불필요) |
| `test_playwright_chrome_channel` 실패 | Chrome이 설치돼 있는지 확인한다. 회사·학교 PC라 Chrome 설치 위치가 다르면 팀 채널에 공유 |
| 라이브러리가 없다는 `ModuleNotFoundError` | `app/` 폴더에서 `uv sync` 실행 (pull 받은 뒤 자주 생김) |
| Linux에서 Qt 창이 안 뜸 (`xcb` 오류) | `sudo apt install libxcb-cursor0` |
| 꼬여서 처음부터 다시 하고 싶음 | `app/.venv` 폴더를 지우고 `uv sync` |
