from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("계정 정리 AI 에이전트")
        self.resize(1000, 700)
        self.setCentralWidget(QLabel("환경 세팅 완료"))
