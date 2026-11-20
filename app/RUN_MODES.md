# 실행 방식별 기능 — `uv run` 개발 실행 vs 빌드 결과물

같은 코드라도 **어떻게 실행하느냐**에 따라 되는 기능이 다르다. 차이는 세 가지에서 나온다.

1. **Gmail 클라이언트 ID**: 빌드에는 CI가 GitHub secret으로 넣어 주고, 개발 실행은 각자 PC에 파일을 둬야 한다.
2. **AI 분류기(ml 그룹)**: 용량(torch 수 GB) 때문에 빌드에 넣지 않는다. 개발 실행에서 `uv sync --group ml`을 한 사람만 쓸 수 있다.
3. **OS**: 빌드는 macOS·Windows만 만든다. 리눅스는 개발 실행만 한다.

> 기준: 2026-11-18 develop (#57까지). 기능이 바뀌면 이 표도 고친다.

---

## 1. 한눈에 보기

| 기능 | `uv run account-cleaner` | 빌드 결과물 (Mac·Windows) | 비고 |
|---|---|---|---|
| 앱 창, 사이드바, 화면 이동 | ✅ | ✅ | |
| MBOX·EML·ZIP 파일 가져오기 | ✅ | ✅ | |
| **Gmail 계정 연결** | ⚠️ 설정 파일을 직접 둬야 함 | ✅ 바로 됨 | [2-1](#2-1-gmail-계정-연결) |
| 네이버 메일 | ❌ 준비 중 | ❌ 준비 중 | #21 보류 |
| **계정 후보 분석 (실제 AI 분류기)** | ⚠️ ml 그룹 + 모델 필요 | ⚠️ 모델을 넣고 직접 빌드할 때만 (CI 빌드는 키워드 가짜 분석기) | [2-2](#2-2-계정-후보-분석) |
| 계정 인벤토리, 상세, 근거 메일 미리보기 | ✅ | ✅ | |
| 로그인·탈퇴 전 조건 안내 | ✅ | ✅ | |
| AI 에이전트 안내 (실제 Chrome) | ✅ Chrome 필요 | ✅ Chrome 필요 | GitHub·Dropbox·LinkedIn 플레이북 |
| 안전 데모 (로컬 가짜 사이트) | ✅ | ✅ | 에이전트 화면의 "안전 데모 (로컬)" |
| 후보·확인 상태·진행 저장, 다시 켜면 복원 | ✅ | ✅ | |
| **근거 메일 암호화 키 보관** | ⚠️ 리눅스는 Secret Service, 없으면 키 파일 | ✅ macOS 키체인 / Windows 자격 증명 관리자 | [2-3](#2-3-근거-메일-암호화-키) |
| 세션 정리, 저장된 로그인 모두 지우기 | ✅ | ✅ | |
| 진행 기록 화면 | ✅ | ✅ | |
| **재알림 시스템 알림 (트레이)** | ⚠️ 리눅스는 데스크톱 환경에 따라 다름 | ✅ | 트레이가 없으면 창 아래 상태 표시줄로 대신함 |
| 리눅스에서 실행 | ✅ | ❌ 빌드 안 만듦 | |
| 더블클릭 실행 (Python·uv 없이) | ❌ | ✅ | |
| `--self-test` (묶인 파일 확인) | ✅ 돌지만 의미 적음 | ✅ CI가 매번 확인 | 빌드에서 Qt·Gmail·키체인·Playwright·Chrome 확인 |

✅ 그대로 됨 · ⚠️ 준비하면 됨 · ❌ 안 됨

---

## 2. 차이가 나는 기능 자세히

### 2-1. Gmail 계정 연결

| | 클라이언트 ID 파일(`google_client_secret.json`)을 찾는 곳 |
|---|---|
| 빌드 결과물 | CI가 GitHub secret `GOOGLE_CLIENT_SECRET_JSON`으로 실행파일 안에 넣는다. **할 일 없음** |
| `uv run` | 아래 순서로 찾는다. 셋 다 없으면 "Gmail 연결 설정 파일을 찾지 못했습니다" |

`uv run`에서 찾는 순서:

1. 환경변수 `ACCOUNT_CLEANER_GOOGLE_CLIENT_SECRET=<json 경로>`
2. 앱 데이터 폴더의 `google_client_secret.json`
   - macOS: `~/Library/Application Support/TEAM-CATHOLIC/AccountCleaner/`
   - Windows: `%APPDATA%\TEAM-CATHOLIC\AccountCleaner\`
   - 리눅스: `~/.local/share/TEAM-CATHOLIC/AccountCleaner/`
3. `src/account_cleaner/resources/google_client_secret.json` (gitignore 대상. 절대 커밋하지 않는다)

공통: Google Cloud 앱이 **테스트 모드**라 OAuth 테스트 사용자로 등록된 계정만 로그인할 수 있다. 토큰은 저장하지 않으므로 가져올 때마다 다시 로그인한다.

로컬에서 직접 `pyinstaller`로 빌드하면 3번 파일이 있을 때만 Gmail 연결이 들어간다. CI 빌드 결과물을 쓰는 것을 권장한다.

### 2-2. 계정 후보 분석

| | 쓰는 분석기 | 결과 |
|---|---|---|
| CI 빌드 결과물 (Actions) | 키워드 가짜 분석기 (`FakeAnalyzer`) | 제목에 "가입·비밀번호·주문·약관·탈퇴 완료" 같은 낱말이 있는지로만 판단한다. **시연 화면 흐름 확인용**이고 정확도는 의미 없다 |
| `uv run` (기본) | 키워드 가짜 분석기 | 빌드와 같다 |
| `uv run` + ml 그룹 + 모델 | 실제 로컬 AI 분류기 (파인튜닝한 E5 임베딩 + 로지스틱 회귀) | 아래 준비가 필요하다 |
| 모델을 넣고 직접 빌드한 결과물 | 실제 로컬 AI 분류기 | 아래 "AI 포함 빌드" |

실제 분류기를 쓰는 방법:

```bash
uv sync --group ml                                   # torch 포함, 수 GB
gh release download model-e5ft-20261120 --repo TEAM-CATHOLIC/eliceContest --pattern classifier-model-e5ft.zip
powershell -Command "Expand-Archive classifier-model-e5ft.zip -DestinationPath src\account_cleaner\classifier\bundled"
uv run account-cleaner
```

- 모델은 용량이 커서 저장소 대신 GitHub Release `model-e5ft-20261120`에 있다 ([CLASSIFIER.md](CLASSIFIER.md)).
- `classifier/bundled/`에 모델이 있으면 환경 변수 없이 그 모델을 쓴다. 다른 모델 폴더를 쓰려면 `ACCOUNT_CLEANER_MODEL_DIR=<모델 폴더>`로 지정한다 (환경 변수가 우선).
- **AI 포함 빌드:** ml 그룹을 설치하고 `bundled/`에 모델을 둔 상태에서 PyInstaller로 빌드하면 실행파일 안에 모델이 들어간다 (Windows 기준 약 1.4GB, zip 약 640MB). CI(Actions) 빌드에는 모델이 없어 키워드 가짜 분석기를 쓴다.
- ml 라이브러리가 없는 빌드 결과물에서 `ACCOUNT_CLEANER_MODEL_DIR`을 지정하면 **분석 단계에서 실패**한다.

### 2-3. 근거 메일 암호화 키

| | 키를 두는 곳 | 사이드바 "엔진 암호화" |
|---|---|---|
| 빌드 (macOS) | macOS 키체인 | 적용 (메일 근거) |
| 빌드 (Windows) | Windows 자격 증명 관리자 | 적용 (메일 근거) |
| `uv run` (macOS·Windows) | 빌드와 같다 | 적용 (메일 근거) |
| `uv run` (리눅스) | Secret Service (GNOME 키링 등). 없으면 앱 데이터 폴더의 `evidence.key` | 적용 (메일 근거) / 적용 (메일 근거, 키 파일) |

- 개발 중에 키체인을 건드리고 싶지 않으면 `ACCOUNT_CLEANER_KEY_STORE=file`을 설정한다. 그러면 키 파일만 쓴다.
- 서명하지 않은 Mac 빌드는 처음 실행하거나 새 빌드로 바꿀 때 키체인 접근 "허용" 창이 뜰 수 있다.
- 키가 바뀌면(다른 빌드, 키체인 초기화) 저장된 근거 메일은 지워지고 "메일을 다시 불러오세요" 안내가 뜬다. 계정 후보와 확인 상태는 남는다.

---

## 3. 개발 실행에서만 쓰는 것

| 명령 | 용도 |
|---|---|
| `uv run pytest` | 테스트 (실제 headless Chrome 테스트 포함) |
| `uv run ruff check src/account_cleaner tests scripts` | 린트 (팀원 원본 폴더는 돌리지 않는다) |
| `uv run python -m account_cleaner.browser.demo` | 로컬 데모 사이트로 브라우저 에이전트만 실행 |
| `uv run python -m account_cleaner.demo_mail --model-dir <모델> --data-dir <폴더>` | 메일 → 분석 → 탈퇴 → 완료 메일 확인까지 한 서비스 시연 (ml 그룹 필요, [MAIL_DEMO.md](MAIL_DEMO.md)) |
| `uv run python scripts/gmail_check.py` | Gmail 가져오기 점검 (건수·시간만 출력) |
| `uv run pyinstaller packaging/account_cleaner.spec` | 로컬 빌드 (Gmail ID는 2-1의 3번 파일이 있을 때만) |

## 4. 두 방식 모두에서 쓰는 설정

빌드 결과물도 터미널에서 실행하면 같은 환경변수·옵션을 쓸 수 있다 (macOS는 `AccountCleaner.app/Contents/MacOS/AccountCleaner`).

| 설정 | 용도 |
|---|---|
| `ACCOUNT_CLEANER_HOME=<폴더>` | 앱 데이터 폴더 바꾸기 (DB·프로필·로그·키 파일) |
| `ACCOUNT_CLEANER_FAKE=agent,playbooks` 등 | 일부를 가짜 구현으로 (`all` / `none` / 쉼표 목록) |
| `ACCOUNT_CLEANER_KEY_STORE=file` | 키체인 대신 키 파일 |
| `ACCOUNT_CLEANER_ALLOW_LOCAL_HTTP=0` | 로컬 http 플레이북 막기 (배포 환경용) |
| `ANTHROPIC_API_KEY=<키>` | 플레이북 없는 사이트의 범용 AI 안내 활성화 |
| `ACCOUNT_CLEANER_LLM_MODEL=claude-haiku-5-5` | 범용 안내 모델 변경 (기본값 `claude-haiku-5-5`) |
| `--import-file <파일...>` | 켜자마자 그 파일 가져오기 |
| `--self-test [--require-chrome]` | 묶인 구성요소 확인 |

처음 상태로 되돌리기: 앱 데이터 폴더를 통째로 지운다. 키체인의 `account-cleaner` 항목은 남아 있어도 된다 (새 DB에 그대로 쓰인다).

개발 중 PowerShell에서는 `$env:ANTHROPIC_API_KEY="..."` 뒤에 앱을 실행한다. 배포 환경에서는
Windows 키체인의 서비스 `account-cleaner`, 사용자명 `anthropic-api-key`에 저장된 값도 읽는다.
API 키가 없으면 기존 플레이북 안내는 그대로 쓸 수 있지만 `AI 안내 (실험)`은 비활성화된다.
