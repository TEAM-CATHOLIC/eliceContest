from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import Action, Playbook
from .policy import SafetyPolicy


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    step: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    service_id: str
    score: int
    valid: bool
    issues: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict:
        return {
            "service_id": self.service_id,
            "score": self.score,
            "valid": self.valid,
            "issues": [asdict(issue) for issue in self.issues],
        }


def validate_playbook(playbook: Playbook) -> ValidationReport:
    policy = SafetyPolicy(playbook.allowed_domains, playbook.auth_domains)
    issues: list[ValidationIssue] = []
    normalized = [domain.casefold().rstrip(".") for domain in playbook.allowed_domains]

    if not playbook.allowed_domains:
        issues.append(ValidationIssue("error", "no_domains", "허용 도메인이 없습니다"))
    if len(set(normalized)) != len(normalized):
        issues.append(
            ValidationIssue("warning", "duplicate_domains", "중복된 허용 도메인이 있습니다")
        )
    normalized_auth = [domain.casefold().rstrip(".") for domain in playbook.auth_domains]
    if len(set(normalized_auth)) != len(normalized_auth):
        issues.append(
            ValidationIssue("warning", "duplicate_auth_domains", "중복된 인증 도메인이 있습니다")
        )
    if set(normalized) & set(normalized_auth):
        issues.append(
            ValidationIssue(
                "error", "auth_domain_overlap", "서비스 도메인과 인증 전용 도메인이 겹칩니다"
            )
        )
    if not policy.is_url_allowed(playbook.entry_url):
        issues.append(
            ValidationIssue("error", "unsafe_entry_url", "시작 URL이 허용 도메인 밖입니다")
        )
    if not playbook.steps:
        issues.append(ValidationIssue("error", "no_steps", "실행 단계가 없습니다"))

    target_steps = 0
    for index, step in enumerate(playbook.steps):
        if not step.description:
            issues.append(
                ValidationIssue("warning", "missing_description", "단계 설명이 없습니다", index)
            )
        if step.action == Action.NAVIGATE and not policy.is_url_allowed(step.value):
            issues.append(
                ValidationIssue(
                    "error", "unsafe_navigation", "허용 도메인 밖으로 이동합니다", index
                )
            )
        if step.action == Action.CLICK:
            candidates = (step.value, *step.fallback_texts)
            if any(policy.is_final_action(candidate) for candidate in candidates):
                issues.append(
                    ValidationIssue(
                        "error",
                        "final_action_click",
                        "최종 탈퇴 동작을 클릭 단계로 정의했습니다",
                        index,
                    )
                )
        if step.action == Action.REACH_TARGET:
            target_steps += 1
            if index != len(playbook.steps) - 1:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "target_not_last",
                        "목표 도달 뒤 실행 단계가 남아 있습니다",
                        index,
                    )
                )

    if target_steps == 0:
        issues.append(
            ValidationIssue("warning", "no_target", "명시적인 탈퇴 화면 도달 단계가 없습니다")
        )

    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    score = max(0, 100 - errors * 30 - warnings * 5)
    return ValidationReport(playbook.service_id, score, errors == 0, tuple(issues))
