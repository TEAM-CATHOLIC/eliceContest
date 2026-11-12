# 계정 정리 AI 에이전트 — 데스크톱 앱

Python 3.12 + PySide6 + Playwright. 기획 문서는 [`../docs`](../docs) 참고.

## 세팅

1. [uv](https://docs.astral.sh/uv/getting-started/installation/) 설치
2. Chrome 설치 (PoC는 설치된 Chrome을 사용)
3. 이 폴더에서:

```bash
uv sync                 # Python 3.12 + 앱 + 개발 도구 설치
uv sync --group ml      # (AI 작업 시) sentence-transformers, scikit-learn 추가
```

## 실행 / 테스트

```bash
uv run account-cleaner  # 앱 실행
uv run pytest           # 테스트
uv run ruff check .     # 린트
```

## 폴더

| 경로 | 내용 |
|---|---|
| `src/account_cleaner/ui/` | PySide6 화면 |
| `src/account_cleaner/browser/` | Playwright, 플레이북, 넘겨주기 |
| `src/account_cleaner/mail/` | MBOX/EML 파싱 |
| `src/account_cleaner/classifier/` | 임베딩 + 로지스틱 회귀 |
| `src/account_cleaner/storage/` | SQLite |
