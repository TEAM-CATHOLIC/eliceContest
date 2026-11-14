"""오래 걸리는 작업(메일 불러오기, 분석, 브라우저 에이전트)을 UI가 멈추지 않게 작업 스레드에서 돌린다.

사용법:

    def job(ctx: TaskContext) -> int:
        for i in range(100):
            ctx.raise_if_cancelled()
            ctx.progress(i + 1, 100)
        return 42

    task = BackgroundTask(job, name="분석")
    task.progress.connect(bar.update)      # UI 스레드에서 불림
    task.succeeded.connect(on_done)
    task.failed.connect(on_error)
    task.start()
    ...
    task.cancel()

규칙:
- 작업 함수는 작업 스레드에서 실행된다. **Qt 위젯을 직접 건드리지 않는다.**
- 시그널(progress/succeeded/failed/cancelled/finished)은 UI 스레드에서 받는다.
- 작업 하나에 스레드 하나. 끝나면 스레드는 정리된다.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any, ClassVar

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

log = logging.getLogger(__name__)


class TaskCancelled(Exception):
    """작업 함수가 취소 요청을 확인하고 멈출 때 던진다."""


class TaskContext:
    """작업 함수에 넘겨지는 도구. 진행률 보고와 취소 확인."""

    def __init__(self, progress: Callable[[int, int], None], cancel_event: threading.Event):
        self._progress = progress
        self._cancel = cancel_event

    def progress(self, done: int, total: int) -> None:
        self._progress(done, total)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise TaskCancelled


class _Runner(QObject):
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    done = Signal()

    def __init__(self, fn: Callable[[TaskContext], Any], cancel_event: threading.Event, name: str):
        super().__init__()
        self._fn = fn
        self._cancel = cancel_event
        self._name = name

    @Slot()
    def run(self) -> None:
        ctx = TaskContext(self.progress.emit, self._cancel)
        try:
            result = self._fn(ctx)
        except TaskCancelled:
            log.info("작업 취소됨: %s", self._name)
            self.cancelled.emit()
        except Exception as e:
            log.exception("작업 실패: %s", self._name)
            self.failed.emit(e)
        else:
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        finally:
            self.done.emit()


class BackgroundTask(QObject):
    progress = Signal(int, int)
    """(처리한 수, 전체 수)"""
    succeeded = Signal(object)
    """작업 함수의 반환값"""
    failed = Signal(object)
    """작업 함수가 던진 예외"""
    cancelled = Signal()
    finished = Signal()
    """성공·실패·취소 어느 경우든 마지막에 한 번"""

    _active: ClassVar[set["BackgroundTask"]] = set()

    def __init__(self, fn: Callable[[TaskContext], Any], name: str = "작업", parent=None):
        super().__init__(parent)
        self.name = name
        self._fn = fn
        self._cancel = threading.Event()
        self._thread: QThread | None = None
        self._runner: _Runner | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError(f"이미 시작한 작업: {self.name}")
        thread = QThread()
        thread.setObjectName(f"task:{self.name}")
        runner = _Runner(self._fn, self._cancel, self.name)
        runner.moveToThread(thread)

        thread.started.connect(runner.run)
        # runner는 작업 스레드, self는 UI 스레드에 있으므로 아래 연결은 자동으로 큐 연결이 된다.
        runner.progress.connect(self.progress)
        runner.succeeded.connect(self.succeeded)
        runner.failed.connect(self.failed)
        runner.cancelled.connect(self.cancelled)
        # quit은 스레드 안전하다. 작업 스레드에서 바로 부르게 해서(Direct), UI 스레드가
        # wait()으로 막혀 있어도(앱 종료 시) 스레드가 끝날 수 있게 한다.
        runner.done.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self._on_thread_finished)

        self._thread, self._runner = thread, runner
        self._started = True
        BackgroundTask._active.add(self)
        thread.start()

    def cancel(self) -> None:
        """취소를 요청한다. 작업 함수가 `ctx.cancelled`를 확인해야 실제로 멈춘다."""
        self._cancel.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def wait(self, timeout_ms: int = 5000) -> bool:
        return self._thread.wait(timeout_ms) if self._thread else True

    @Slot()
    def _on_thread_finished(self) -> None:
        if self._runner:
            self._runner.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._thread = self._runner = None
        BackgroundTask._active.discard(self)
        self.finished.emit()

    @classmethod
    def shutdown_all(cls, timeout_ms: int = 3000) -> None:
        """앱 종료 시 돌고 있는 작업을 모두 취소하고 잠시 기다린다."""
        tasks = list(cls._active)
        for t in tasks:
            t.cancel()
        for t in tasks:
            if not t.wait(timeout_ms):
                log.warning("작업이 제때 끝나지 않음: %s", t.name)
