"""로그인 방식 — 분석 결과와 플레이북이 함께 쓴다."""

from enum import StrEnum


class LoginMethod(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    GOOGLE = "google"
    KAKAO = "kakao"
    NAVER = "naver"
    APPLE = "apple"
