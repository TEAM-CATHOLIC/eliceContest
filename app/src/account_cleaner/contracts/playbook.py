"""플레이북 — 브라우저 담당이 서비스별 JSON으로 작성하고, 데스크톱(안내 화면)과 에이전트가 읽는다."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from account_cleaner.contracts.login import LoginMethod

SCHEMA_VERSION = 1


class PlaybookError(ValueError):
    """플레이북 JSON 형식이 잘못됐다."""


def host_matches(host: str, domains: tuple[str, ...]) -> bool:
    """`host`가 `domains` 중 하나이거나 그 하위 도메인인지.

    "a.shop.example.com"은 "shop.example.com"에 맞지만 "evilshop.example.com"은 맞지 않는다.
    """
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


@dataclass(frozen=True, slots=True)
class Playbook:
    """서비스 하나의 로그인·복구·탈퇴 경로 (PRD F-05~F-07).

    약속:
    - 모든 URL은 https이고, 호스트가 `domains`(또는 그 하위 도메인)에 속한다.
    - 에이전트는 `domains`와 `auth_domains` 밖으로 이동하지 않는다 (PRD 5장 도메인 제한).
    - `auth_domains`는 소셜 로그인·본인인증용 외부 도메인이다. 이 도메인에서는 에이전트가
      조작하지 않고 사용자에게 넘긴다 (논의사항 D-02, 미확정).
    - `steps`의 형식은 브라우저 담당이 정한다. 데스크톱은 내용을 해석하지 않는다.
    """

    id: str
    """파일 이름과 같은 영문 식별자. 예: "sample_shop" """
    service: str
    """화면에 보일 서비스명. `AccountCandidate.service`와 매칭할 때도 쓴다."""
    domains: tuple[str, ...]
    login_methods: tuple[LoginMethod, ...]
    login_url: str
    password_reset_url: str
    withdraw_url: str
    auth_domains: tuple[str, ...] = ()
    pre_withdraw_conditions: tuple[str, ...] = ()
    """탈퇴 전에 사용자가 확인해야 할 조건 (구독, 잔액, 데이터 삭제 등)."""
    steps: tuple[dict[str, Any], ...] = ()

    def allows(self, url: str) -> bool:
        """에이전트가 `url`로 이동해도 되는지."""
        parts = urlsplit(url)
        return parts.scheme == "https" and host_matches(
            parts.hostname or "", self.domains + self.auth_domains
        )

    def matches_domain(self, domain: str) -> bool:
        """계정 후보 도메인이 이 서비스 것인지."""
        return host_matches(domain, self.domains)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Playbook":
        def req(key: str) -> Any:
            if key not in data:
                raise PlaybookError(f"필수 필드 없음: {key}")
            return data[key]

        if data.get("schema_version") != SCHEMA_VERSION:
            raise PlaybookError(f"schema_version은 {SCHEMA_VERSION}이어야 함")
        try:
            methods = tuple(LoginMethod(m) for m in req("login_methods"))
        except ValueError as e:
            raise PlaybookError(f"알 수 없는 로그인 방식: {e}") from e

        pb = cls(
            id=req("id"),
            service=req("service"),
            domains=tuple(d.lower() for d in req("domains")),
            login_methods=methods,
            login_url=req("login_url"),
            password_reset_url=req("password_reset_url"),
            withdraw_url=req("withdraw_url"),
            auth_domains=tuple(d.lower() for d in data.get("auth_domains", ())),
            pre_withdraw_conditions=tuple(data.get("pre_withdraw_conditions", ())),
            steps=tuple(data.get("steps", ())),
        )
        if not pb.domains:
            raise PlaybookError(f"{pb.id}: domains가 비어 있음")
        for name in ("login_url", "password_reset_url", "withdraw_url"):
            url = getattr(pb, name)
            parts = urlsplit(url)
            if parts.scheme != "https" or not host_matches(parts.hostname or "", pb.domains):
                raise PlaybookError(f"{pb.id}: {name}는 domains 안의 https 주소여야 함: {url}")
        return pb


def load_playbook(path: Path) -> Playbook:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlaybookError(f"{path.name}: JSON 형식 오류: {e}") from e
    pb = Playbook.from_dict(data)
    if pb.id != path.stem:
        raise PlaybookError(f"{path.name}: id({pb.id})가 파일 이름과 다름")
    return pb


def load_playbooks(directory: Path) -> dict[str, Playbook]:
    """폴더 안의 `*.json`을 모두 읽는다. 하나라도 잘못되면 `PlaybookError`."""
    return {pb.id: pb for pb in map(load_playbook, sorted(directory.glob("*.json")))}
