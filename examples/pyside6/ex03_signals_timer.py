# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""Signals, slots and QTimer.

Run: uv run ex03_signals_timer.py

Shows:
- The device only emits signals and never imports widgets.
  The window connects those signals to its labels.
- QTimer runs code later or repeatedly without blocking the GUI.

Try: connect `battery_changed` to `print` as well.
"""

import random
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class FakeDevice(QObject):
    battery_changed = Signal(int)
    status_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.battery = 100
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self.drain_battery)

    def connect_device(self) -> None:
        self.status_changed.emit("connecting...")
        QTimer.singleShot(1000, self.on_connected)

    def disconnect_device(self) -> None:
        self.timer.stop()
        self.status_changed.emit("disconnected")

    def on_connected(self) -> None:
        self.status_changed.emit("connected")
        self.timer.start()

    def drain_battery(self) -> None:
        self.battery = max(0, self.battery - random.randint(0, 3))
        self.battery_changed.emit(self.battery)


class Window(QWidget):
    def __init__(self, device: FakeDevice) -> None:
        super().__init__()
        self.setWindowTitle("03 - Signals and QTimer")
        status = QLabel("disconnected")
        battery = QProgressBar(minimum=0, maximum=100, value=100)
        connect_button = QPushButton("Connect")
        disconnect_button = QPushButton("Disconnect")

        layout = QVBoxLayout(self)
        for widget in (status, battery, connect_button, disconnect_button):
            layout.addWidget(widget)

        connect_button.clicked.connect(device.connect_device)
        disconnect_button.clicked.connect(device.disconnect_device)
        device.status_changed.connect(status.setText)
        device.battery_changed.connect(battery.setValue)


def main() -> None:
    app = QApplication(sys.argv)
    device = FakeDevice()
    window = Window(device)
    window.resize(320, 160)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
