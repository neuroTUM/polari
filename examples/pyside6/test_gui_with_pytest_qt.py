"""GUI tests with pytest-qt.

Run:
    uv run --with PySide6-Essentials==6.12.0 --with pyqtgraph==0.14.0 --with numpy \
        --with pytest --with pytest-qt pytest test_gui_with_pytest_qt.py

`qtbot` creates the QApplication, types, clicks and waits for signals.
Set QT_QPA_PLATFORM=offscreen to run without windows, e.g. in CI.
"""

import numpy as np
from PySide6.QtCore import Qt

from ex03_signals_timer import FakeDevice
from ex04_thread_live_plot import RingBuffer
from ex05_model_view import ExperimentTableModel, sample_rows
from ex06_form_validation import NewExperimentForm


def make_form(qtbot) -> NewExperimentForm:
    form = NewExperimentForm()
    qtbot.addWidget(form)
    return form


def test_empty_form_marks_title_invalid(qtbot):
    form = make_form(qtbot)
    form.submit()
    assert form.errors["title"].text()
    assert form.title.property("invalid")


def test_typing_clears_the_error(qtbot):
    form = make_form(qtbot)
    form.submit()
    qtbot.keyClicks(form.title, "MI baseline")
    assert not form.title.property("invalid")


def test_valid_form_shows_json(qtbot):
    form = make_form(qtbot)
    qtbot.keyClicks(form.title, "MI baseline")
    qtbot.keyClicks(form.pilot, "p18")
    form.purpose.setPlainText("Motor imagery baseline")
    qtbot.keyClicks(form.date, "14-11-2026")
    qtbot.mouseClick(form.create_button, Qt.MouseButton.LeftButton)
    assert "MI baseline" in form.preview.toPlainText()


def test_pilot_field_blocks_spaces_and_slashes(qtbot):
    form = make_form(qtbot)
    qtbot.keyClicks(form.pilot, "p 1/8")
    assert form.pilot.text() == "p18"


def test_device_reports_battery_after_connecting(qtbot):
    device = FakeDevice()
    with qtbot.waitSignal(device.battery_changed, timeout=3000):
        device.connect_device()


def test_model_add_row_notifies_views(qtbot):
    model = ExperimentTableModel(sample_rows())
    with qtbot.waitSignal(model.rowsInserted):
        model.add(sample_rows()[0])
    assert model.rowCount() == 5


def test_ring_buffer_keeps_newest_samples():
    buffer = RingBuffer(channels=1, capacity=5)
    buffer.write(np.array([[0, 1, 2, 3]], dtype=np.float32))
    buffer.write(np.array([[4, 5, 6]], dtype=np.float32))
    assert buffer.oldest_first()[0].tolist() == [2, 3, 4, 5, 6]
