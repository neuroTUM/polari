# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0", "qasync==0.28.0"]
# ///
"""asyncio inside Qt with qasync (the "asyncio + Qt bridge" from the whiteboard).

Run: uv run ex10_asyncio_qasync.py

Shows:
- qasync runs asyncio on Qt's event loop, so `await` code and widgets share one thread.
- A fake device is an async generator; start/stop = create/cancel a task.
- Use this when the device library is async (e.g. bleak for BLE).
  Use a QThread (ex04) when it blocks or uses callbacks (e.g. explorepy).

Try: replace asyncio.sleep with time.sleep and watch the window freeze.
"""

import asyncio
import sys
import time

import qasync
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget


async def fake_device(rate: int = 250, packet_ms: int = 40):
    """Yields the number of samples in each packet, like a BLE device would."""
    while True:
        await asyncio.sleep(packet_ms / 1000)
        yield rate * packet_ms // 1000


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("10 - asyncio + Qt (qasync)")
        self.resize(360, 160)
        self.task: asyncio.Task | None = None
        self.label = QLabel("idle")
        start_button = QPushButton("Start")
        start_button.clicked.connect(self.start)
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop)

        layout = QVBoxLayout(self)
        for widget in (self.label, start_button, stop_button):
            layout.addWidget(widget)

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.stream())

    def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def stream(self) -> None:
        total = 0
        started = time.monotonic()
        try:
            async for samples in fake_device():
                total += samples
                rate = total / (time.monotonic() - started)
                self.label.setText(f"samples: {total}   rate: {rate:.0f} Hz")
        except asyncio.CancelledError:
            self.label.setText(f"stopped after {total} samples")
            raise


async def main() -> None:
    closed = asyncio.Event()
    QApplication.instance().aboutToQuit.connect(closed.set)
    window = Window()
    window.show()
    window.start()
    await closed.wait()
    window.stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    asyncio.run(main(), loop_factory=qasync.QEventLoop)
