"""작업이 진행 중임을 보여 주는 표시 (#83): 움직이는 막대 + 지금 하는 일 + 걸린 시간.

[▬▬▬▬━━━━━━━━]  AI가 다음 화면을 찾는 중 · 0:12

QProgressBar의 '바쁨' 애니메이션은 스타일시트를 입히면 OS마다 안 움직일 수 있어 직접 그린다.
"""

from PySide6.QtCore import QElapsedTimer, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from account_cleaner.ui.theme import set_role, tokens

FRAME_MS = 30
SEGMENT = 0.32
"""막대 전체 폭 중 움직이는 조각의 비율"""


class MovingBar(QWidget):
    """왼쪽에서 오른쪽으로 계속 흐르는 짧은 막대. `paused`면 멈추고 옅게 보인다."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(6)
        self.setMinimumWidth(96)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._phase = 0.0
        self.paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    def sizeHint(self) -> QSize:
        return QSize(140, 6)

    def start(self) -> None:
        self.paused = False
        self._timer.start()
        self.update()

    def pause(self) -> None:
        self.paused = True
        self._timer.stop()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.018) % (1 + SEGMENT)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        painter.setBrush(QColor(tokens.GRAY_200))
        painter.drawRoundedRect(rect, radius, radius)
        if self.paused:
            painter.setBrush(QColor(tokens.GRAY_600))
            painter.drawRoundedRect(
                QRectF(0, 0, rect.width() * SEGMENT, rect.height()), radius, radius
            )
            return
        width = rect.width() * SEGMENT
        left = (self._phase - SEGMENT) * rect.width()
        segment = QRectF(left, 0, width, rect.height()).intersected(rect)
        if segment.width() > 0:
            painter.setBrush(QColor(tokens.ACCENT))
            painter.drawRoundedRect(segment, radius, radius)


def elapsed_text(seconds: int) -> str:
    minutes, seconds = divmod(max(seconds, 0), 60)
    return f"{minutes}:{seconds:02d}"


class RunIndicator(QWidget):
    """움직이는 막대 + "지금 하는 일 · 0:12". 작업 시작~끝까지 보인다."""

    def __init__(self) -> None:
        super().__init__()
        self.bar = MovingBar()
        self.label = set_role(QLabel(), "role", "label")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_3)
        layout.addWidget(self.bar)
        layout.addWidget(self.label, 1)
        self._text = ""
        self._clock = QElapsedTimer()
        self._seconds = QTimer(self)
        self._seconds.setInterval(1000)
        self._seconds.timeout.connect(self._render)
        self.hide()

    def start(self, text: str) -> None:
        self._clock.start()
        self._seconds.start()
        self.set_phase(text)
        self.show()

    def set_phase(self, text: str, waiting: bool = False) -> None:
        """지금 하는 일. waiting=True면 사람 차례라 막대를 멈춘다."""
        self._text = text
        if waiting:
            self.bar.pause()
        else:
            self.bar.start()
        self._render()

    def stop(self) -> None:
        self.bar.stop()
        self._seconds.stop()
        self.hide()

    def text(self) -> str:
        return self.label.text()

    def _render(self) -> None:
        seconds = self._clock.elapsed() // 1000 if self._clock.isValid() else 0
        self.label.setText(f"{self._text} · {elapsed_text(seconds)}")
