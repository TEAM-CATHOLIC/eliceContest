"""계정 후보 목록 한 줄 그리기 (#66).

┌────────────────────────────────────────────────────────────────┐
│ [G]  GitHub  github.com                      계정 있음   [확정] │
│      가입·인증 1 · 보안·복구 1 · 마지막 메일 2026.10.19               │
└────────────────────────────────────────────────────────────────┘
글이 넘치면 말줄임(…)으로 줄이고, 전체 내용은 툴팁(모델의 ToolTipRole)으로 보여 준다.
"""

from zlib import crc32

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from account_cleaner.contracts import AccountCandidate
from account_cleaner.ui.candidates.model import (
    CandidateStatus,
    Role,
    evidence_summary,
    has_account,
    verdict_label,
)
from account_cleaner.ui.theme import tokens

ROW_HEIGHT = 64
GAP = 2
AVATAR = 38
BAR_WIDTH = 72
BADGE_WIDTH = 64

AVATAR_TINTS = (tokens.BLUE, tokens.GREEN, tokens.PURPLE, tokens.YELLOW, tokens.RED, tokens.NEUTRAL)
STATUS_TONES = {
    CandidateStatus.UNREVIEWED: tokens.NEUTRAL,
    CandidateStatus.CONFIRMED: tokens.ACCENT_PAIR,
    CandidateStatus.EXCLUDED: tokens.NEUTRAL,
    CandidateStatus.DEFERRED: tokens.YELLOW,
    CandidateStatus.IN_PROGRESS: tokens.BLUE,
    CandidateStatus.DONE: tokens.GREEN,
}


def display_name(service: str) -> str:
    """분석기가 준 이름이 소문자 영문(github)이면 첫 글자만 대문자로. 한글·대소문자 섞인 이름은 그대로."""
    return service[:1].upper() + service[1:] if service.isascii() and service.islower() else service


def avatar_tint(domain: str) -> tuple[str, str]:
    """도메인마다 늘 같은 색 (실행할 때마다 바뀌지 않게 crc32)."""
    return AVATAR_TINTS[crc32(domain.encode()) % len(AVATAR_TINTS)]


def meta_text(candidate: AccountCandidate) -> str:
    return f"{evidence_summary(candidate)} · 마지막 메일 {candidate.last_seen:%Y.%m.%d}"


def _font(base: QFont, style: tokens.TextStyle) -> QFont:
    font = QFont(base)
    font.setPixelSize(style.size)
    font.setWeight(QFont.Weight(style.weight))
    return font


class CandidateDelegate(QStyledItemDelegate):
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT + GAP)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        candidate: AccountCandidate = index.data(Role.CANDIDATE)
        status = CandidateStatus(index.data(Role.STATUS))
        rect = option.rect.adjusted(0, 0, 0, -GAP)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(QColor(tokens.ACCENT_SOFT))
            painter.drawRoundedRect(rect, tokens.RADIUS + 2, tokens.RADIUS + 2)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QColor(tokens.GRAY_100))
            painter.drawRoundedRect(rect, tokens.RADIUS + 2, tokens.RADIUS + 2)

        left = rect.left() + tokens.SPACE_3
        right = rect.right() - tokens.SPACE_3
        # 상태 배지 (오른쪽 끝)
        badge = QRect(right - BADGE_WIDTH + 1, rect.center().y() - 12, BADGE_WIDTH, 24)
        self._pill(painter, badge, status.label, STATUS_TONES[status], option.font)
        right = badge.left() - tokens.SPACE_4
        # 판정 (숫자 대신 "계정 있음 / 확인 안 됨")
        bar_left = right - BAR_WIDTH + 1
        painter.setFont(_font(option.font, tokens.CAPTION))
        painter.setPen(QColor(tokens.ACCENT if has_account(candidate) else tokens.GRAY_600))
        painter.drawText(
            QRect(bar_left, rect.top(), BAR_WIDTH, rect.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            verdict_label(candidate),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        right = bar_left - tokens.SPACE_4
        # 첫 글자 아바타
        avatar = QRect(left, rect.center().y() - AVATAR // 2, AVATAR, AVATAR)
        background, foreground = avatar_tint(candidate.domain)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(avatar, tokens.RADIUS, tokens.RADIUS)
        name = display_name(candidate.service)
        painter.setFont(_font(option.font, tokens.TextStyle(15, 700)))
        painter.setPen(QColor(foreground))
        painter.drawText(avatar, Qt.AlignmentFlag.AlignCenter, name[:1])
        # 이름 + 도메인 / 근거 요약
        x = avatar.right() + 1 + 14
        width = max(0, right - x)
        name_font = _font(option.font, tokens.TextStyle(15, 600))
        domain_font = _font(option.font, tokens.CAPTION)
        name_width = min(QFontMetrics(name_font).horizontalAdvance(name) + 2, width)
        top_line = QRect(x, rect.top() + 11, width, 22)
        self._text(
            painter,
            top_line.adjusted(0, 0, name_width - width, 0),
            name,
            name_font,
            tokens.GRAY_1000,
        )
        domain_left = x + name_width + tokens.SPACE_2
        self._text(
            painter,
            QRect(domain_left, top_line.top() + 1, max(0, right - domain_left), 22),
            candidate.domain,
            domain_font,
            tokens.GRAY_700,
        )
        self._text(
            painter,
            QRect(x, rect.top() + 34, width, 20),
            meta_text(candidate),
            domain_font,
            tokens.GRAY_800,
        )
        painter.restore()

    @staticmethod
    def _text(painter: QPainter, rect: QRect, text: str, font: QFont, color: str) -> None:
        if rect.width() <= 0:
            return
        painter.setFont(font)
        painter.setPen(QColor(color))
        elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.setPen(Qt.PenStyle.NoPen)

    @staticmethod
    def _pill(
        painter: QPainter, rect: QRect, text: str, tone: tuple[str, str], base: QFont
    ) -> None:
        background, foreground = tone
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setFont(_font(base, tokens.TextStyle(tokens.CAPTION.size, 600)))
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(Qt.PenStyle.NoPen)
