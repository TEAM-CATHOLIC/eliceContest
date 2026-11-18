"""앱 전체 스타일시트. 화면 코드는 색·크기를 직접 쓰지 않고 아래 속성만 붙인다.

- 글자: `QLabel[role="title" | "titleSmall" | "subtitle" | "label" | "body" | "caption" | "muted" | "number"]`
- 버튼: `QPushButton[variant="primary" | "soft" | "ghost" | "choice"]` (없으면 흰 바탕 보조 버튼).
  "choice"는 고른 값이 꺼진(disabled) 상태로 표시될 때 메인 색으로 보인다
- 카드: `QFrame[card="true"]` 흰 바탕 둥근 상자, `QFrame[card="subtle"]` 옅은 회색 상자
"""

from account_cleaner.ui.theme import tokens as t
from account_cleaner.ui.theme.icons import Icon, icon_file


def _text(role: str, style: t.TextStyle, color: str = t.GRAY_1000) -> str:
    return (
        f'QLabel[role="{role}"] {{ font-size: {style.size}px; font-weight: {style.weight};'
        f" color: {color}; }}"
    )


def build_stylesheet() -> str:
    chevron = icon_file(Icon.CHEVRON_DOWN, t.GRAY_800)
    check = icon_file(Icon.CHECK, t.ON_ACCENT)
    roles = "\n".join(
        [
            _text("title", t.TITLE),
            _text("titleSmall", t.TITLE_SMALL),
            _text("subtitle", t.SUBTITLE),
            _text("label", t.LABEL),
            _text("body", t.BODY, t.GRAY_900),
            _text("caption", t.CAPTION, t.GRAY_800),
            _text("muted", t.BODY_SMALL, t.GRAY_800),
            _text("number", t.NUMBER),
        ]
    )
    return f"""
QMainWindow, QDialog, QMessageBox {{ background: {t.GRAY_100}; }}
QWidget {{ color: {t.GRAY_1000}; }}
QLabel {{ background: transparent; }}
{roles}
QLabel[role="number"][accent="true"], QLabel[role="caption"][accent="true"] {{ color: {t.ON_ACCENT}; }}

QFrame[card="true"] {{ background: {t.WHITE}; border: none; border-radius: {t.RADIUS_PANEL}px; }}
QFrame[card="subtle"] {{ background: {t.GRAY_100}; border: none; border-radius: {t.RADIUS + 2}px; }}
QFrame[card="accent"] {{ background: {t.ACCENT}; border: none; border-radius: {t.RADIUS_CARD}px; }}

QPushButton {{
    background: {t.WHITE}; color: {t.GRAY_900};
    border: 1px solid {t.GRAY_400}; border-radius: {t.RADIUS}px;
    padding: 0 {t.SPACE_4}px; min-height: {t.CONTROL_HEIGHT - 2}px;
    font-size: {t.BODY_SMALL.size}px; font-weight: 500;
}}
QPushButton:hover {{ background: {t.GRAY_100}; }}
QPushButton:pressed {{ background: {t.GRAY_200}; }}
QPushButton:disabled {{ color: {t.GRAY_600}; border-color: {t.GRAY_300}; background: {t.WHITE}; }}
QPushButton[variant="primary"] {{
    background: {t.ACCENT}; color: {t.ON_ACCENT}; border: none;
    min-height: {t.CONTROL_HEIGHT}px; font-size: {t.BODY.size}px; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {t.ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {t.ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:disabled {{ background: {t.GRAY_300}; color: {t.GRAY_700}; }}
QPushButton[variant="soft"] {{
    background: {t.ACCENT_SOFT}; color: {t.ACCENT}; border: 1px solid {t.ACCENT}; font-weight: 600;
}}
QPushButton[variant="choice"]:disabled {{
    background: {t.ACCENT_SOFT}; color: {t.ACCENT}; border: 1px solid {t.ACCENT}; font-weight: 600;
}}
QPushButton[variant="ghost"] {{ background: transparent; border: none; color: {t.GRAY_800}; }}
QPushButton[variant="ghost"]:hover {{ background: {t.GRAY_200}; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {t.WHITE}; color: {t.GRAY_1000};
    border: 1px solid {t.GRAY_400}; border-radius: {t.RADIUS}px;
    selection-background-color: {t.ACCENT_SOFT}; selection-color: {t.GRAY_1000};
}}
QLineEdit, QComboBox, QSpinBox {{ padding: 0 {t.SPACE_3}px; min-height: {t.CONTROL_HEIGHT - 2}px; }}
QPlainTextEdit, QTextEdit {{ padding: {t.SPACE_2}px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t.ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {t.WHITE}; border: 1px solid {t.GRAY_300}; border-radius: {t.RADIUS_SMALL}px;
    padding: {t.SPACE_1}px; outline: 0;
    selection-background-color: {t.ACCENT_SOFT}; selection-color: {t.GRAY_1000};
}}

QListView, QListWidget, QTableView, QTableWidget, QTreeView {{
    background: {t.WHITE}; border: none; border-radius: {t.RADIUS}px; outline: 0;
    alternate-background-color: {t.GRAY_100};
}}
QListView::item, QListWidget::item {{ padding: {t.SPACE_2}px {t.SPACE_3}px; border-radius: {t.RADIUS_SMALL}px; }}
QListView::item:hover, QListWidget::item:hover, QTableView::item:hover {{ background: {t.GRAY_100}; }}
QListView::item:selected, QListWidget::item:selected, QTableView::item:selected {{
    background: {t.ACCENT_SOFT}; color: {t.GRAY_1000};
}}
QTableView, QTableWidget {{ gridline-color: {t.GRAY_300}; }}
QTableView::item {{ padding: 0 {t.SPACE_2}px; }}
QHeaderView::section {{
    background: {t.WHITE}; color: {t.GRAY_800}; font-weight: 600;
    border: none; border-bottom: 1px solid {t.GRAY_300}; padding: {t.SPACE_2}px;
}}

QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {t.GRAY_800}; border: none; border-radius: {t.RADIUS_SMALL}px;
    padding: 6px {t.SPACE_3}px; margin: 3px 1px; font-size: {t.BODY_SMALL.size}px;
}}
QTabBar::tab:selected {{ background: {t.WHITE}; color: {t.GRAY_1000}; font-weight: 600; }}
QTabBar::tab:hover:!selected {{ color: {t.GRAY_1000}; }}

QCheckBox, QRadioButton {{ spacing: {t.SPACE_2}px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1.5px solid {t.GRAY_600}; background: {t.WHITE};
}}
QCheckBox::indicator:checked {{ background: {t.ACCENT}; border-color: {t.ACCENT}; image: url("{check}"); }}

QProgressBar {{
    background: {t.GRAY_200}; border: none; border-radius: 4px; max-height: 8px; text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {t.ACCENT}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t.GRAY_400}; border-radius: 3px; min-height: 32px; min-width: 32px; }}
QScrollBar::handle:hover {{ background: {t.GRAY_600}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {t.GRAY_1000}; color: {t.WHITE}; border: none;
    border-radius: 6px; padding: 6px {t.SPACE_2}px;
}}
QStatusBar {{ background: {t.GRAY_100}; color: {t.GRAY_800}; }}
QStatusBar QLabel {{ color: {t.GRAY_800}; }}
QSplitter::handle {{ background: transparent; }}
"""
