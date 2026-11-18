# 가져다 쓴 디자인 자산과 라이선스

앱 디자인(#66)에 쓴 외부 자산이다. 라이선스 원문은 앱과 함께 배포된다 (`src/account_cleaner/ui/theme/` 아래).

| 자산 | 쓴 곳 | 라이선스 | 원문 |
|---|---|---|---|
| Pretendard 1.3.9 | 앱 글꼴 (Regular·Medium·SemiBold·Bold, 원본 그대로) | SIL Open Font License 1.1 | `ui/theme/fonts/OFL.txt` |
| Tabler Icons 3.35.0 | 메뉴·버튼 아이콘 (SVG 원본, 색만 바꿔 그림) | MIT | `ui/theme/icons/LICENSE` |
| SEED Design (당근) | 회색 단계·상태 색·글자 크기·간격·모서리 값 | Apache License 2.0 | `ui/theme/SEED-LICENSE.txt`, `ui/theme/SEED-NOTICE.txt` |

## Pretendard

Copyright (c) 2021, Kil Hyung-jin (https://github.com/orioncactus/pretendard), with Reserved Font Name Pretendard.
SIL Open Font License 1.1에 따라 원본 글꼴 파일을 수정하지 않고 앱에 포함한다. 글꼴만 따로 판매하지 않는다.

## Tabler Icons

MIT License, Copyright (c) 2020-2025 Paweł Kuna. https://github.com/tabler/tabler-icons

## SEED Design

SEED Design, Copyright 2025 주식회사 당근마켓. https://github.com/daangn/seed-design
Apache License 2.0에 따라 디자인 기준값(색 코드·크기 숫자)을 가져와 썼다 (`ui/theme/tokens.py`).
보조 글자 회색 한 단계(`GRAY_700`)는 글자 대비를 위해 더 진하게 바꿨다.

당근마켓의 로고·상호·캐릭터 등 브랜드 리소스와 당근 브랜드 색(주황)은 쓰지 않는다.
이 앱은 당근마켓과 제휴·후원·보증 관계가 없다.

## 토스

토스 디자인 시스템(TDS)은 공개 라이선스가 아니므로 색·컴포넌트·이미지를 가져오지 않았다.
