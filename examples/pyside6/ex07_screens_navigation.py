# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""The 4 polari screens in one window with QStackedWidget.

Run: uv run ex07_screens_navigation.py

Shows:
- QStackedWidget holds several pages and shows one at a time:
  Experiments -> New experiment -> Recording -> Save.
- Screens only emit signals; the main window alone decides where to go next.
- Navigation is locked while recording.

Try: add an "Impedance check" screen between New experiment and Recording.
"""

import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class ExperimentsScreen(QWidget):
    new_requested = Signal()
    open_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.list = QListWidget()
        self.list.addItems(["MI baseline p18", "SSVEP pilot p03"])
        self.list.itemDoubleClicked.connect(lambda item: self.open_requested.emit(item.text()))
        new_button = QPushButton("+ New experiment")
        new_button.clicked.connect(self.new_requested)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Experiments</h2>"))
        layout.addWidget(self.list, 1)
        layout.addWidget(new_button)


class NewExperimentScreen(QWidget):
    created = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.title = QLineEdit(placeholderText="Title")
        create_button = QPushButton("Create")
        create_button.clicked.connect(lambda: self.created.emit(self.title.text() or "Untitled"))
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancelled)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(create_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>New experiment</h2>(the full form is in ex06)"))
        layout.addWidget(self.title)
        layout.addStretch()
        layout.addLayout(buttons)


class RecordingScreen(QWidget):
    recording_changed = Signal(bool)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.heading = QLabel()
        self.clock = QLabel("00:00", alignment=Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet("font-size: 48px;")
        self.seconds = 0
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self.tick)

        self.record_button = QPushButton("Start recording", checkable=True)
        self.record_button.toggled.connect(self.on_record_toggled)
        self.finish_button = QPushButton("Finish experiment")
        self.finish_button.clicked.connect(self.finished)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(QLabel("(the live plot from ex04 and the head map from ex08 go here)"))
        layout.addWidget(self.clock, 1)
        layout.addWidget(self.record_button)
        layout.addWidget(self.finish_button)

    def set_experiment(self, title: str) -> None:
        self.heading.setText(f"<h2>Recording: {title}</h2>")

    def on_record_toggled(self, recording: bool) -> None:
        self.record_button.setText("Stop recording" if recording else "Start recording")
        self.finish_button.setEnabled(not recording)
        if recording:
            self.seconds = 0
            self.timer.start()
        else:
            self.timer.stop()
        self.recording_changed.emit(recording)

    def tick(self) -> None:
        self.seconds += 1
        minutes, seconds = divmod(self.seconds, 60)
        self.clock.setText(f"{minutes:02d}:{seconds:02d}")


class SaveScreen(QWidget):
    done = Signal()

    def __init__(self) -> None:
        super().__init__()
        save_button = QPushButton("Save and go to experiments")
        save_button.clicked.connect(self.done)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Save experiment</h2>Export plots, PDF, raw data (see ex09)."))
        layout.addStretch()
        layout.addWidget(save_button)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("07 - Screens")
        self.resize(700, 500)

        self.experiments = ExperimentsScreen()
        self.new_experiment = NewExperimentScreen()
        self.recording = RecordingScreen()
        self.save = SaveScreen()

        self.stack = QStackedWidget()
        for screen in (self.experiments, self.new_experiment, self.recording, self.save):
            self.stack.addWidget(screen)
        self.setCentralWidget(self.stack)

        self.back = self.menuBar().addAction("Back to experiments")
        self.back.triggered.connect(lambda: self.go(self.experiments))

        self.experiments.new_requested.connect(lambda: self.go(self.new_experiment))
        self.experiments.open_requested.connect(self.open_recording)
        self.new_experiment.cancelled.connect(lambda: self.go(self.experiments))
        self.new_experiment.created.connect(self.on_created)
        self.recording.recording_changed.connect(lambda on: self.back.setEnabled(not on))
        self.recording.finished.connect(lambda: self.go(self.save))
        self.save.done.connect(lambda: self.go(self.experiments))

    def go(self, screen: QWidget) -> None:
        self.stack.setCurrentWidget(screen)

    def on_created(self, title: str) -> None:
        self.experiments.list.addItem(title)
        self.open_recording(title)

    def open_recording(self, title: str) -> None:
        self.recording.set_experiment(title)
        self.go(self.recording)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
