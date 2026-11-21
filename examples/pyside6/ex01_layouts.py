# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""Main window, layouts, splitter, menu, toolbar and status bar.

Run: uv run ex01_layouts.py

Shows:
- Layouts place and resize widgets for you; no pixel positions anywhere.
- A QAction is one command shared by the menu, the toolbar and a shortcut.

Try: drag the splitter, resize the window, press Cmd+N.
"""

import sys

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def form_page() -> QWidget:
    page = QWidget()
    form = QFormLayout(page)
    form.addRow("Title", QLineEdit(placeholderText="e.g. MI baseline"))
    form.addRow("Pilot", QLineEdit(placeholderText="e.g. p18"))
    form.addRow("Tiredness", QSpinBox(minimum=0, maximum=10))
    return page


def grid_page() -> QWidget:
    page = QWidget()
    grid = QGridLayout(page)
    for i in range(12):
        row, col = divmod(i, 4)
        grid.addWidget(QPushButton(f"Ch {i + 1}"), row, col)
    return page


def box_page() -> QWidget:
    page = QWidget()
    buttons = QHBoxLayout()
    for name in ("Connect", "Start", "Stop"):
        buttons.addWidget(QPushButton(name))
    buttons.addStretch()

    layout = QVBoxLayout(page)
    layout.addLayout(buttons)
    layout.addStretch()
    return page


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("01 - Layouts")
        self.resize(900, 550)

        self.experiments = QListWidget()
        self.experiments.addItems(["MI baseline p18", "SSVEP pilot p03", "ArrowGame p07"])
        self.experiments.currentTextChanged.connect(self.on_selected)

        tabs = QTabWidget()
        tabs.addTab(form_page(), "QFormLayout")
        tabs.addTab(grid_page(), "QGridLayout")
        tabs.addTab(box_page(), "QHBox / QVBox")

        splitter = QSplitter()
        splitter.addWidget(self.experiments)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(1, 3)
        splitter.setHandleWidth(6)  # the default handle is hard to find in dark mode
        self.setCentralWidget(splitter)

        new_action = QAction("New experiment", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.on_new)
        self.menuBar().addMenu("&File").addAction(new_action)
        self.addToolBar("Main").addAction(new_action)

        self.statusBar().addPermanentWidget(QLabel("Device: not connected"))

    def on_selected(self, text: str) -> None:
        self.statusBar().showMessage(f"Selected: {text}", 2000)

    def on_new(self) -> None:
        self.experiments.addItem(f"New experiment {self.experiments.count() + 1}")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
