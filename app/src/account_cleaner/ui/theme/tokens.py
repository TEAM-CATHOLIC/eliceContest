"""디자인 기준값 (#66, A안 청록).

회색 단계·상태 색·글자 크기·간격·모서리는 당근 SEED 디자인 시스템(Apache-2.0)의 값을 따른다.
메인 색(청록)은 우리 것이다. 출처와 라이선스: app/THIRD_PARTY_NOTICES.md
"""

from dataclasses import dataclass

# 메인 색
ACCENT = "#0b7a75"
ACCENT_HOVER = "#096560"
ACCENT_PRESSED = "#07524e"
ACCENT_SOFT = "#e7f2f1"
"""메인 색 10% (흰 바탕 위). 선택된 줄, 보조 버튼 바탕"""
ON_ACCENT = "#ffffff"

# 회색 (SEED palette gray, light)
WHITE = "#ffffff"
GRAY_100 = "#f7f8f9"
"""창 바탕"""
GRAY_200 = "#f3f4f5"
GRAY_300 = "#eeeff1"
"""옅은 테두리·구분선"""
GRAY_400 = "#dcdee3"
"""입력칸·버튼 테두리"""
GRAY_600 = "#b0b3ba"
GRAY_700 = "#6c727c"
"""보조 글자 (도메인, 날짜). SEED #868b94는 흰 바탕 대비 3.4:1이라 작은 글자용으로 4.6:1 이상까지 진하게"""
GRAY_800 = "#555d6d"
"""설명 글자"""
GRAY_900 = "#2a3038"
GRAY_1000 = "#1a1c20"
"""본문 글자"""

# 상태 색: (바탕, 글자). SEED palette 100 / 800 단계 — 글자 대비 4.5:1 이상
BLUE = ("#eff6ff", "#135fcd")
GREEN = ("#edfaf6", "#00745f")
YELLOW = ("#fff7de", "#755b22")
RED = ("#fdf0f0", "#ca1d13")
PURPLE = ("#f5f3fe", "#6d50cb")
NEUTRAL = (GRAY_200, GRAY_800)
ACCENT_PAIR = (ACCENT_SOFT, ACCENT)

FONT_FAMILY = "Pretendard"
FONT_FALLBACKS = ("Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", "sans-serif")


@dataclass(frozen=True)
class TextStyle:
    size: int
    """px"""
    weight: int


# 글자 단계 (SEED t2~t10)
CAPTION = TextStyle(12, 400)
BODY_SMALL = TextStyle(13, 400)
BODY = TextStyle(14, 400)
LABEL = TextStyle(14, 600)
SUBTITLE = TextStyle(16, 600)
TITLE_SMALL = TextStyle(18, 700)
TITLE = TextStyle(24, 700)
NUMBER = TextStyle(26, 700)

# 간격 (4px 단위)
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24

# 모서리
RADIUS_SMALL = 8
RADIUS = 10
RADIUS_CARD = 14
RADIUS_PANEL = 16

CONTROL_HEIGHT = 40
"""버튼·입력칸 기본 높이 (클릭 영역 40px 이상)"""
