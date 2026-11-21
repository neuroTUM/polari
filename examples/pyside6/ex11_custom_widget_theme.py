# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""A custom painted widget (status LED) and an app-wide light/dark theme.

Run: uv run ex11_custom_widget_theme.py

Shows:
- StatusLed draws itself in paintEvent; update() asks Qt to repaint it.
- A stream health panel: one row per LSL stream, coloured by packet loss.
- One app.setStyleSheet() call themes the whole app.

Try: make the LED blink when the state is BAD.
"""

import random
import sys
from enum import Enum

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class Health(Enum):
    OK = "#2ca02c"
    WARN = "#e6b800"
    BAD = "#d62728"
    OFF = "#888888"


class StatusLed(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.state = Health.OFF
        self.setFixedSize(18, 18)

    def set_state(self, state: Health) -> None:
        self.state = state
        self.setToolTip(state.name)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#333"))
        painter.setBrush(QColor(self.state.value))
        painter.drawEllipse(self.rect().adjusted(2, 2, -2, -2))


LIGHT = """
QWidget { background: #fafafa; color: #222; font-size: 13px; }
QPushButton { background: #e8e8e8; border: 1px solid #bbb; border-radius: 4px; padding: 4px 10px; }
"""
DARK = """
QWidget { background: #1e1f22; color: #ddd; font-size: 13px; }
QPushButton { background: #2d2f33; border: 1px solid #555; border-radius: 4px; padding: 4px 10px; }
"""

STREAMS = [("Explore_8441", "EEG", 250), ("Smarting", "EEG", 250), ("ArrowGame", "Markers", None)]


def health_for_loss(loss: float) -> Health:
    # 1 % / 5 % are the thresholds from the problem report; still an open question.
    if loss < 0.01:
        return Health.OK
    if loss < 0.05:
        return Health.WARN
    return Health.BAD


class HealthPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("11 - Custom widget + theme")
        self.dark = False

        grid = QGridLayout()
        for col, heading in enumerate(["", "Stream", "Type", "Expected", "Measured"]):
            grid.addWidget(QLabel(f"<b>{heading}</b>"), 0, col)
        self.rows = []
        for row, (name, kind, rate) in enumerate(STREAMS, start=1):
            led, measured = StatusLed(), QLabel("-")
            grid.addWidget(led, row, 0)
            grid.addWidget(QLabel(name), row, 1)
            grid.addWidget(QLabel(kind), row, 2)
            grid.addWidget(QLabel(f"{rate} Hz" if rate else "irregular"), row, 3)
            grid.addWidget(measured, row, 4)
            self.rows.append((led, measured, rate))

        theme_button = QPushButton("Toggle dark theme")
        theme_button.clicked.connect(self.toggle_theme)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addStretch()
        layout.addWidget(theme_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.timer = QTimer(self, interval=700)
        self.timer.timeout.connect(self.fake_measurement)
        self.timer.start()

    def fake_measurement(self) -> None:
        for led, label, rate in self.rows:
            if rate is None:
                led.set_state(Health.OK)
                label.setText("last marker 1.2 s ago")
                continue
            measured = rate * random.uniform(0.9, 1.0)
            loss = 1 - measured / rate
            label.setText(f"{measured:.0f} Hz ({loss:.0%} loss)")
            led.set_state(health_for_loss(loss))

    def toggle_theme(self) -> None:
        self.dark = not self.dark
        QApplication.instance().setStyleSheet(DARK if self.dark else LIGHT)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(LIGHT)
    panel = HealthPanel()
    panel.resize(520, 220)
    panel.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
