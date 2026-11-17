"""One-service synthetic MVP demo using the real local analyzer and browser agent.

python -m account_cleaner.demo_mail --model-dir <local weights> --data-dir <local demo data>
"""

import argparse
import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.classifier import create_analyzer
from account_cleaner.classifier.completion import find_completion
from account_cleaner.contracts import AgentStatus
from account_cleaner.demo_mail_flow import DOMAIN, SERVICE, DemoSession, start_site
from account_cleaner.mail import FileMailSource
from account_cleaner.pipeline import run_pipeline
from account_cleaner.ui.agent_page import AgentPage
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage
from account_cleaner.ui.workers import BackgroundTask


class DemoWindow(QMainWindow):
    def __init__(self, data_dir, analyzer_factory=create_analyzer, agent_factory=None):
        super().__init__()
        from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent

        self.setWindowTitle("계정 정리 MVP · 모아북 메일 시연")
        self.resize(1300, 880)
        self.session = DemoSession(Path(data_dir))
        self.server, playbook = start_site(self.session)
        playbook = replace(playbook, service=SERVICE)
        self._analyzer_factory = analyzer_factory
        self._analyzer = None
        self._analysis_task = None
        self._known_ids = set()
        self.completed = False
        self.completion_evidence = None
        self.inventory = InventoryPage()
        self.agent = AgentPage(
            self.session.root / "browser-profile",
            agent_factory=agent_factory or PlaywrightWithdrawAgent,
            playbook_loader=lambda: {playbook.id: playbook},
            include_demo=False,
        )
        self.playbook = playbook
        self.inventory.detail.set_playbook_lookup(self.agent.playbook_for_domain)
        self.inventory.agent_requested.connect(lambda _candidate: self.start_guide())
        self.agent.run_finished.connect(self._agent_event)

        central = QWidget()
        layout = QVBoxLayout(central)
        title = QLabel("메일에서 찾고, 탈퇴를 안내하고, 새 완료 메일로 확인합니다")
        title.setStyleSheet("font-size:22px;font-weight:700;padding:10px")
        note = QLabel(
            "시연용 가상 서비스와 합성 메일만 사용합니다. 실제 계정·비밀번호·외부 메일 전송은 없습니다.\n"
            "로컬 분류기 + 명시적 완료 문구 기준 / 실제 브라우저 에이전트 / 마지막 버튼은 사용자가 누릅니다."
        )
        note.setWordWrap(True)
        self.load_button = QPushButton("1. 이용 메일 분석")
        self.guide_button = QPushButton("2. 탈퇴 화면 안내")
        self.check_button = QPushButton("3. 완료 메일 다시 확인")
        self.guide_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.load_button.clicked.connect(self.load_usage)
        self.guide_button.clicked.connect(self.start_guide)
        self.check_button.clicked.connect(self.check_completion)
        buttons = QHBoxLayout()
        for button in (self.load_button, self.guide_button, self.check_button):
            buttons.addWidget(button)
        self.status = QLabel("1번을 눌러 시연용 가입 완료 메일 1통을 분석하세요.")
        self.status.setWordWrap(True)
        self.model_info = QLabel(
            "모델: 이 PC의 multilingual-e5-small + 로컬 분류 가중치 (v1) · 아직 불러오기 전"
        )
        self.model_info.setWordWrap(True)
        self.notification = QLabel("")
        self.notification.setObjectName("completionNotification")
        self.notification.setWordWrap(True)
        self.notification.setStyleSheet("background:#e4f2e5;padding:15px;font-weight:600")
        self.notification.hide()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.inventory, "서비스 후보와 근거 메일")
        self.tabs.addTab(self.agent, "브라우저 안내")
        for widget in (title, note):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addWidget(self.model_info)
        layout.addWidget(self.notification)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_demo_mail)
        self.timer.start(1000)

    def _analyze(self, paths, completion):
        if self._analysis_task is not None:
            return
        self.load_button.setEnabled(False)
        self.guide_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.status.setText(
            "로컬에서 메일을 분석 중입니다. 처음에는 모델을 불러오는 시간이 필요합니다."
        )

        def job(ctx):
            if self._analyzer is None:
                self._analyzer = self._analyzer_factory()
            return run_pipeline(
                lambda _cancel: (FileMailSource(paths), None),
                self._analyzer,
                lambda _stage, done, total: ctx.progress(done, total),
                lambda: ctx.cancelled,
            )

        task = BackgroundTask(job, name="demo-mail-analysis", parent=self)
        self._analysis_task = task
        task.succeeded.connect(lambda outcome: self._show_result(outcome, completion))
        task.failed.connect(
            lambda error: self.status.setText(
                f"분석 실패: {type(error).__name__}. 모델 설정을 확인하세요."
            )
        )
        task.finished.connect(self._analysis_finished)
        task.start()

    def load_usage(self):
        if self.session.started_at is None:
            self._analyze([self.session.usage_path], False)

    def _show_result(self, outcome, completion):
        self.model_info.setText(
            "모델 불러오기 완료: 이 PC의 E5 임베딩 + v1 분류 가중치 · 외부 AI API 호출 없음"
        )
        candidates = [replace(c, service=SERVICE) for c in outcome.candidates if c.domain == DOMAIN]
        self.inventory.set_candidates(candidates)
        self.inventory.detail.set_mail_lookup(outcome.mail_lookup())
        if candidates:
            self.inventory.select_row(0)
        self.tabs.setCurrentIndex(0)
        if not completion:
            self._known_ids = {m.id for m in outcome.mails}
            self.status.setText(
                "이용 흔적을 찾았습니다. 2번을 누르면 Chrome에서 시연 서비스의 탈퇴 화면까지 안내합니다."
            )
            return
        evidence = find_completion(outcome.mails, DOMAIN, self.session.started_at, self._known_ids)
        if evidence is None:
            self.status.setText(
                "완료 확인 대기: 새 메일의 서비스·날짜·명시적 탈퇴 완료 문구가 모두 필요합니다."
            )
            return
        self.completed = True
        self.completion_evidence = evidence
        self.inventory.set_status(DOMAIN, CandidateStatus.DONE)
        self.status.setText("시연 완료: 새로 생성된 탈퇴 완료 메일을 확인했습니다.")
        self.notification.setText(
            "탈퇴 완료 메일 확인 — 모아북 (시연)\n"
            f"{evidence.received_at.astimezone():%Y-%m-%d %H:%M:%S} · {evidence.statement}\n"
            "합성 메일을 이용한 시연 결과입니다. 실제 서비스 탈퇴를 확인한 것은 아닙니다."
        )
        self.notification.show()

    def _analysis_finished(self):
        self._analysis_task = None
        self.load_button.setEnabled(self.session.started_at is None)
        self.guide_button.setEnabled(bool(self._known_ids) and self.session.started_at is None)
        self.check_button.setEnabled(self.session.reached and not self.completed)

    def start_guide(self):
        if (
            not self._known_ids
            or self.session.started_at is not None
            or self._analysis_task is not None
        ):
            return
        self.session.start()
        self.guide_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.tabs.setCurrentIndex(1)
        self.status.setText(
            "Chrome에서 '시연 계정으로 계속'을 누른 뒤, 앱의 '직접 처리했어요, 계속'을 누르세요. "
            "실제 비밀번호는 필요 없습니다."
        )
        self.agent.start_for(self.playbook.id)

    def _agent_event(self, event):
        if event.status is AgentStatus.REACHED:
            self.session.reached = True
            self.check_button.setEnabled(True)
            self.status.setText(
                "탈퇴 화면 도착은 완료가 아닙니다. Chrome의 '계정 영구 삭제 (시연용 메일 생성)'를 직접 누르세요. "
                "완료 메일이 생기면 앱에서 자동 확인합니다."
            )
        elif not self.completed:
            self.status.setText(
                "브라우저 안내가 중단됐습니다. 새 시연을 시작하려면 이 시연 창을 다시 실행하세요."
            )

    def _poll_demo_mail(self):
        if (
            self.session.reached
            and not self.completed
            and self._analysis_task is None
            and self.session.completion_path.exists()
        ):
            self.check_completion()

    def check_completion(self):
        if self.session.started_at is None or not self.session.reached or self.completed:
            return
        if not self.session.completion_path.exists():
            self.status.setText(
                "완료 메일을 기다리고 있습니다. 탈퇴 화면 도착만으로 완료 처리하지 않습니다."
            )
            return
        self._analyze([self.session.usage_path, self.session.completion_path], True)

    def closeEvent(self, event):
        self.timer.stop()
        self.agent.stop()
        BackgroundTask.shutdown_all()
        self.server.shutdown()
        self.server.server_close()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    os.environ["ACCOUNT_CLEANER_MODEL_DIR"] = str(args.model_dir.resolve())
    app = QApplication([])
    app.setApplicationName("AccountCleanerMailDemo")
    window = DemoWindow(args.data_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
