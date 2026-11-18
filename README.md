# 계정 정리 AI 에이전트

오래된 메일함에서 잊힌 계정을 로컬 AI로 찾아내고, 사용자가 직접 인증하면 탈퇴 화면까지 안전하게 데려다주는 Mac/Windows 데스크톱 앱.

| 폴더 | 내용 |
|---|---|
| [`docs/`](docs) | 기획 문서 — PRD, 기술 스택 ADR, 논의사항 |
| [`app/`](app) | 데스크톱 앱 (Python 3.12 + PySide6 + Playwright) |

**앱을 처음 써 본다면 [화면별 사용 가이드](docs/06_화면별_사용가이드.md)부터 본다.**

**개발 환경 세팅은 [`app/README.md`](app/README.md)를 따라 한다.** 요약:

```bash
git clone https://github.com/TEAM-CATHOLIC/eliceContest.git
cd eliceContest/app
uv sync
uv run pytest
```
