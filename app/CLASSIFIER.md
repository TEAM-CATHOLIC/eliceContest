# 로컬 메일 분류기 연결

`ParsedMail` 목록을 받아 실제 로컬 모델과 명시적 규칙으로 증거를 분류하고, 서비스별 `AccountCandidate`를 돌려준다. UI와 브라우저 코드는 변경하지 않는다. 이 변경은 역할 간 인터페이스 PR #18을 기반으로 한다.

## 기존 앱 실행과 실제 AI 선택

`ACCOUNT_CLEANER_MODEL_DIR`가 없으면 기존 auto 모드는 FakeAnalyzer를 유지한다. `ACCOUNT_CLEANER_FAKE=none`에서는 미설정 오류를 낸다. 경로를 명시했는데 파일이 없으면 오류를 내며 가짜 분석 결과로 숨기지 않는다. 일반 UI 개발에는 ML 라이브러리나 모델이 필요 없다.

실제 AI를 사용할 때는 app 폴더에서:

```powershell
uv sync --group ml
$env:ACCOUNT_CLEANER_MODEL_DIR = 'C:\local-only\classifier-artifacts'
# 분석기만 실제 구현. 브라우저/플레이북은 현재 Fake를 유지.
$env:ACCOUNT_CLEANER_FAKE = 'agent,playbooks'
uv run --group ml account-cleaner
```

모델 폴더에는 `manifest.json`과 `weights.json`이 필요하다. manifest의 `model_path`는 해당 PC에 내려받아진 E5 스냅샷 디렉터리여야 한다. 다른 PC에서 절대경로를 그대로 복사하지 않는다. 현재 코드의 기본 추론은 CPU, 512토큰 제한, 8통 단위 배치다. 파일 접근·추론 시 모델 다운로드와 메일 외부 API 호출은 하지 않는다.

모델을 처음 마련할 때는 메일을 열기 전에 공식 공개 모델 `intfloat/multilingual-e5-small`을 별도로 내려받는다. 배포 전 모델 라이선스·용량과 동봉 여부를 확인한다. ML 라이브러리를 보존하려면 이후 실행에도 `--group ml`을 붙인다.

## 학습과 명령행 추론

이 저장소에는 실제 메일·수신 제목·메일 ID 목록·라벨 검토 화면·학습 가중치를 넣지 않는다. 아래 데이터는 사용자가 승인한 로컬 비공개 JSONL로 준비한다.

각 학습 레코드의 필수 필드:

```json
{"id":"synthetic-1","subject":"샘플 제목","body_text":"샘플 본문","label":"signup","split_group":"sample-service","training_eligible":true,"user_verified":true}
```

label은 signup/security/activity/terms/deleted/promo 중 하나다. `user_verified`는 실제로 검토한 경우에만 true로 적는다. 검토 초안을 실험하려면 `--allow-draft`를 명시해야 한다. 같은 서비스·공유 발신 업체·템플릿 변형은 같은 split_group으로 묶는다. 각 유형에 독립적인 서비스 그룹이 부족하면 학습 점검을 중단한다.

```powershell
uv run --group ml python -m account_cleaner.classifier.model train --input 'C:\local-only\labels.jsonl' --model-path 'C:\local-only\e5-snapshot' --output 'C:\local-only\classifier-artifacts'
uv run --group ml python -m account_cleaner.classifier.model predict --input 'C:\local-only\new-mails.jsonl' --output 'C:\local-only\predictions.jsonl' --artifacts 'C:\local-only\classifier-artifacts'
```

학습은 고정 E5 임베딩 + class-balanced 로지스틱 회귀이며 언어모델 파인튜닝이 아니다. 같은 분할로 문자 TF-IDF 비교 모델도 평가한다. 분류 계수는 JSON으로 저장해 실행 가능한 pickle 로딩과 Python/sklearn 버전 결합을 피했다. 모델과 라이브러리는 각 PC에서 별도로 준비해야 한다.

추론 출력은 순수 모델 결과(model_type/model_score)와 보조 규칙 적용 결과(type/decision_source/rule_reason)를 구별한다. classification_score는 선택된 유형의 원래 모델 점수이고 규칙의 정확도가 아니다. 평가 보고서는 순수 모델 점검이며 규칙 정확도를 섞지 않는다.

## 역할 경계와 제한

메일 파서 → `ParsedMail` → `classifier.create_analyzer().analyze(...)` → `AccountCandidate` → 저장소/화면 → 사용자 확인 → 별도 브라우저 에이전트 순서다. 이 코드는 브라우저 로그인이나 최종 탈퇴를 수행하지 않는다. 가입 화면 스크린샷 OCR·화면 파서는 범위 밖이며 후속 플레이북 작성 보조 기능으로 분리할 수 있다.

- 진행률·취소·중복 ID 제거·빈 입력을 지원한다. UI 객체에는 접근하지 않는다.
- 광고/초대만 있는 서비스도 점수 0의 약한 흔적으로 보존하며, 화면에서 가입 미확인임을 설명한다. 결제대행사 발신은 상점 계정과 구별하며 알려지지 않은 매핑은 보류한다.
- 가입 인증 요청·가입 거절을 가입 완료로 단정하지 않는다. 계정 후보 점수는 보정되지 않은 순위 휴리스틱이며 검증된 존재 확률이 아니다.
- 삭제 근거 이후 더 최근의 가입 근거가 있으면 날짜순으로 판단한다. contracts의 has_deleted_evidence는 과거 삭제 근거 존재만 뜻하므로 현재 탈퇴 상태로 표시하면 안 된다.
- 명시적 로그인 방식 추출은 아직 제공하지 않으며 confirmed_login_method는 None이다.
- 사용자 검증 전 소량 데이터로 실행 확인한 개발 버전이다. 탈퇴 완료 자료 부족, 모델의 낮은 점수, 긴 본문 잘림, 미등록 서비스 도메인 정규화는 후속 검증 대상이다. 대회 최종 성능이나 완전 자율 에이전트로 설명하지 않는다.

## 서비스 구분과 데스크톱 실행

Google 계정 데이터 공유 알림은 제목에 명시된 연결 앱을 서비스로 구분한다. 일반 Google 보안 알림은 Google로 남긴다. Cafe24는 제목의 쇼핑몰 브랜드를 구분한다. 알려진 별칭은 `classifier/services.py`에 정의하며, 이것은 학습된 모델의 서비스 식별 성능이 아니다.

서비스명만 있고 대표 주소를 확인하지 못한 경우 `unresolved-<해시>.invalid`를 목록 상태의 구분 키로 사용한다. 실제 웹사이트 주소가 아니며 플레이북·브라우저 이동 주소로 사용하지 않는다. 동일 발신자를 쓰는 서로 다른 브랜드가 한 계정으로 합쳐지지 않게 하기 위한 값이다. 메일 내용만으로 로그인 방식이나 현재 활성 상태를 확정하지 않는다.

모델의 삭제 분류는 명시적 완료 근거와 구별하여 화면에서 '삭제 추정 · 검토 필요'로 표시한다. 과거 삭제 완료 근거가 있어도 이후 재가입과 현재 상태를 확인하도록 설명한다. `has_deleted_evidence`는 유형 존재만 반환하므로 모델 추정과 명시적 완료를 자체적으로 구분하지 못한다. 현재 화면은 근거 점수 1.0의 명시적 규칙과 그 미만의 모델 추정을 구별한다. 모델 원본 결과는 바꾸거나 가입 라벨로 덮어쓰지 않는다.

모델 생성도 가져오기 작업 스레드에서 실행하며, 모델 경로·로딩 오류는 화면에 작업 실패로 전달한다. 아래 옵션은 기존 파일 가져오기 흐름을 실행 직후 시작한다. 실제 Gmail 재연결이나 토큰 없이 로컬 파일로 연결을 점검할 수 있다.

```powershell
uv run --group ml account-cleaner --import-file 'C:\local-only\sample.mbox'
```

로컬 점검에서는 실제 수신 날짜가 보존된 마스킹 메일 51통을 사용하여 파일 파서 → 실제 LocalAccountAnalyzer → 계정 후보 48개 → 인벤토리와 본문 미리보기 연결을 확인했다. 전체 메일함이나 정답 라벨에 대한 정확도 측정이 아니다. 이 점검의 브라우저/플레이북은 Fake이며 실제 사이트 탈퇴 안내 완료를 뜻하지 않는다. 메일 데이터와 모델 가중치는 저장소에 포함하지 않는다.

## 관련성 판정 (선택)

모델 폴더에 `gate.json`이 있으면 6종 유형 분류와 별도로 메일의 관련성(usage/promo/requested/scheduled/suspicious/unrelated)을 판정한다. 파일이 없으면 기존 동작 그대로다. 확률이 파일에 적힌 임계값 미만이면 판정하지 않는다. 명시적 규칙이 결정한 메일은 건드리지 않는다. 의심·업무 메일은 후보 근거에서 빼고, 광고는 점수 0의 약한 흔적으로 낮춘다. 6종 유형 계약과 가중치는 바꾸지 않는다.

가중치는 AI 보조 판정 라벨로 학습한 개발 버전이며 독립 평가 정확도가 아니다. 학습 자료와 가중치는 저장소에 넣지 않는다.

## 검증

기본 테스트는 합성 ParsedMail과 가짜 predictor를 사용해 네트워크·사적인 메일·ML 의존성 없이 실행한다. 실제 로컬 모델 추론은 ML 그룹과 로컬 가중치로 별도로 점검한다.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
