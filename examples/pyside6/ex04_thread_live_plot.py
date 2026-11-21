# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0", "pyqtgraph==0.14.0", "numpy"]
# ///
"""Live EEG plot: worker thread -> ring buffer -> 30 fps redraw.

Run: uv run ex04_thread_live_plot.py

Shows:
- A fake device in a QThread emits chunks (channels x samples), not single samples.
- The GUI copies each chunk into a ring buffer and redraws on its own 30 fps timer,
  so the sample rate and the screen refresh rate are independent.
- Lost packets are NaN and drawn as gaps, not as a fake straight line.

Try: 64 channels at 1000 Hz with packet loss, and watch the frame time.
"""

import sys
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

WINDOW_SECONDS = 10
FPS = 30
CHANNEL_SPACING = 100  # vertical offset between channels, in µV
PACKET_MS = 40
LOSS_PROBABILITY = 0.05


class FakeEeg(QObject):
    """Lives in a worker thread. Emits one chunk per fake Bluetooth packet."""

    chunk_ready = Signal(object)  # np.ndarray, shape (channels, samples)

    def __init__(self, channels: int, rate: int, packet_loss: bool) -> None:
        super().__init__()
        self.channels = channels
        self.rate = rate
        self.packet_loss = packet_loss
        self.samples_sent = 0
        self.rng = np.random.default_rng()
        self.phase = self.rng.uniform(0, 2 * np.pi, (channels, 1))

    def start(self) -> None:
        self.start_time = time.perf_counter()
        self.timer = QTimer()  # created here so it belongs to the worker thread
        self.timer.timeout.connect(self.send_packet)
        self.timer.start(PACKET_MS)

    def stop(self) -> None:
        self.timer.stop()  # a timer must be stopped from its own thread
        QThread.currentThread().quit()

    def send_packet(self) -> None:
        # Send as many samples as real time says are due, so timer jitter never drifts.
        due = int((time.perf_counter() - self.start_time) * self.rate)
        n = due - self.samples_sent
        if n <= 0:
            return
        t = (self.samples_sent + np.arange(n)) / self.rate
        alpha_10hz = 20 * np.sin(2 * np.pi * 10 * t + self.phase)
        chunk = (alpha_10hz + self.rng.normal(0, 8, (self.channels, n))).astype(np.float32)
        if self.packet_loss and self.rng.random() < LOSS_PROBABILITY:
            chunk[:] = np.nan
        self.chunk_ready.emit(chunk)
        self.samples_sent += n


class RingBuffer:
    """Keeps the last `capacity` samples per channel. Writing never allocates."""

    def __init__(self, channels: int, capacity: int) -> None:
        self.data = np.full((channels, capacity), np.nan, dtype=np.float32)
        self.capacity = capacity
        self.next = 0

    def write(self, chunk: np.ndarray) -> None:
        chunk = chunk[:, -self.capacity :]
        indices = (self.next + np.arange(chunk.shape[1])) % self.capacity
        self.data[:, indices] = chunk
        self.next = (self.next + chunk.shape[1]) % self.capacity

    def oldest_first(self) -> np.ndarray:
        return np.roll(self.data, -self.next, axis=1)


class MainWindow(QMainWindow):
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("04 - Thread + live plot")
        self.resize(1200, 800)
        self.thread_: QThread | None = None
        self.device: FakeEeg | None = None
        self.buffer: RingBuffer | None = None

        self.channels = QSpinBox(minimum=1, maximum=128, value=32)
        self.rate = QComboBox()
        self.rate.addItems(["250", "500", "1000", "2000"])
        self.packet_loss = QCheckBox("Simulate packet loss")
        self.packet_loss.toggled.connect(self.on_packet_loss_toggled)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop", enabled=False)
        self.stop_button.clicked.connect(self.stop)

        controls = QHBoxLayout()
        for widget in (
            QLabel("Channels"),
            self.channels,
            QLabel("Hz"),
            self.rate,
            self.packet_loss,
            self.start_button,
            self.stop_button,
        ):
            controls.addWidget(widget)
        controls.addStretch()

        pg.setConfigOptions(antialias=False)  # thin, non-antialiased lines are much faster
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "time", units="s")
        self.plot.hideAxis("left")
        self.plot.setMouseEnabled(x=True, y=False)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(controls)
        layout.addWidget(self.plot, 1)
        self.setCentralWidget(central)

        self.redraw_timer = QTimer(self, interval=1000 // FPS)
        self.redraw_timer.timeout.connect(self.redraw)

    def start(self) -> None:
        channels, rate = self.channels.value(), int(self.rate.currentText())
        self.buffer = RingBuffer(channels, WINDOW_SECONDS * rate)
        self.time_axis = np.linspace(-WINDOW_SECONDS, 0, self.buffer.capacity, dtype=np.float32)
        self.samples = self.lost = 0
        self.frame_times: list[float] = []
        self.setup_curves(channels)

        self.thread_ = QThread()
        self.device = FakeEeg(channels, rate, self.packet_loss.isChecked())
        self.device.moveToThread(self.thread_)
        self.thread_.started.connect(self.device.start)
        self.stop_requested.connect(self.device.stop)
        self.device.chunk_ready.connect(self.on_chunk)  # delivered on the GUI thread
        self.thread_.start()

        self.redraw_timer.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop(self) -> None:
        self.redraw_timer.stop()
        if self.thread_ is not None:
            # Dropping a running QThread crashes the app, so wait until it has finished.
            self.stop_requested.emit()
            self.thread_.wait()
            self.stop_requested.disconnect()
            self.thread_ = self.device = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def setup_curves(self, channels: int) -> None:
        self.plot.clear()
        self.curves = []
        for i in range(channels):
            curve = self.plot.plot(pen=pg.intColor(i, channels), connect="finite")
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            curve.setPos(0, -i * CHANNEL_SPACING)
            self.curves.append(curve)
        self.plot.setYRange(-(channels - 0.5) * CHANNEL_SPACING, CHANNEL_SPACING / 2)
        self.plot.setXRange(-WINDOW_SECONDS, 0)

    def on_packet_loss_toggled(self, on: bool) -> None:
        if self.device is not None:
            self.device.packet_loss = on

    def on_chunk(self, chunk: np.ndarray) -> None:
        # A chunk from an already stopped device can still arrive after a restart.
        if self.buffer is None or chunk.shape[0] != self.buffer.data.shape[0]:
            return
        self.buffer.write(chunk)
        self.samples += chunk.shape[1]
        if np.isnan(chunk[0, 0]):
            self.lost += chunk.shape[1]

    def redraw(self) -> None:
        started = time.perf_counter()
        for curve, channel in zip(self.curves, self.buffer.oldest_first(), strict=True):
            curve.setData(self.time_axis, channel)
        self.frame_times.append((time.perf_counter() - started) * 1000)

        if len(self.frame_times) == FPS:
            self.statusBar().showMessage(
                f"samples/channel: {self.samples}   lost: {self.lost}   "
                f"setData per frame: median {np.median(self.frame_times):.1f} ms"
            )
            self.frame_times.clear()

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    app.aboutToQuit.connect(window.stop)  # Cmd+Q does not always call closeEvent
    window.show()
    window.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
