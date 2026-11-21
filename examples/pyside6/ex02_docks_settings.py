# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""Dock widgets, and QSettings to remember where they are.

Run: uv run ex02_docks_settings.py

Shows:
- QDockWidget panels can be dragged, tabbed, floated or closed.
  Fits the recording screen: plot in the middle, panels around it.
- QSettings stores the layout per user, so it is back after a restart.

Try: move the docks, quit, start again. View > Reset layout.
"""

import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QWidget,
)

Area = Qt.DockWidgetArea


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("02 - Docks and settings")
        self.resize(1000, 600)
        self.settings = QSettings("neuroTUM", "pyside6-examples")

        plot = QLabel("Live EEG plot goes here", alignment=Qt.AlignmentFlag.AlignCenter)
        plot.setStyleSheet("background: #111; color: #8f8; font-size: 20px;")
        self.setCentralWidget(plot)

        streams = QListWidget()
        streams.addItems(["Explore_8441 (EEG, 32 ch, 250 Hz)", "ArrowGame (Markers)"])
        markers = QListWidget()
        markers.addItems(["12.03 s  left", "15.51 s  right", "19.02 s  rest"])
        log = QPlainTextEdit("10:51:02 connected\n10:51:05 recording started", readOnly=True)

        view_menu = self.menuBar().addMenu("&View")
        for title, widget, area in [
            ("Streams", streams, Area.LeftDockWidgetArea),
            ("Markers", markers, Area.RightDockWidgetArea),
            ("Log", log, Area.BottomDockWidgetArea),
        ]:
            dock = self.add_dock(title, widget, area)
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        view_menu.addAction("Reset layout", self.reset_layout)

        self.default_state = self.saveState()  # taken before restoring, for "Reset"
        self.restoreGeometry(self.settings.value("geometry", b""))
        self.restoreState(self.settings.value("state", b""))

    def add_dock(self, title: str, widget: QWidget, area: Area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title)  # saveState() finds docks by object name
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def reset_layout(self) -> None:
        self.restoreState(self.default_state)
        for dock in self.findChildren(QDockWidget):
            dock.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
