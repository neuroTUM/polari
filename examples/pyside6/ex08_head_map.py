# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0", "pyqtgraph==0.14.0", "numpy"]
# ///
"""Electrode head map with live quality colours.

Run: uv run ex08_head_map.py

Shows:
- One ScatterPlotItem draws all 32 electrodes; recolouring them is one call.
- Clicking an electrode toggles it on or off.
- A fake impedance changes every 0.5 s: green < 20, yellow < 50, else red (kOhm).

Try: change the thresholds in `quality_color`.
"""

import sys

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

# shortcut: rough 2D positions of the 10-20 system; read them from the layout file later.
# fmt: off
ELECTRODES = {
    "Fp1": (-0.25, 0.76), "Fp2": (0.25, 0.76), "AF3": (-0.27, 0.58), "AF4": (0.27, 0.58),
    "F7": (-0.65, 0.47), "F3": (-0.33, 0.42), "Fz": (0.0, 0.40), "F4": (0.33, 0.42),
    "F8": (0.65, 0.47), "FC5": (-0.55, 0.20), "FC1": (-0.18, 0.20), "FC2": (0.18, 0.20),
    "FC6": (0.55, 0.20), "T7": (-0.80, 0.0), "C3": (-0.40, 0.0), "Cz": (0.0, 0.0),
    "C4": (0.40, 0.0), "T8": (0.80, 0.0), "CP5": (-0.55, -0.20), "CP1": (-0.18, -0.20),
    "CP2": (0.18, -0.20), "CP6": (0.55, -0.20), "P7": (-0.65, -0.47), "P3": (-0.33, -0.42),
    "Pz": (0.0, -0.40), "P4": (0.33, -0.42), "P8": (0.65, -0.47), "PO3": (-0.27, -0.58),
    "PO4": (0.27, -0.58), "O1": (-0.25, -0.76), "Oz": (0.0, -0.80), "O2": (0.25, -0.76),
}
# fmt: on
NAMES = list(ELECTRODES)
DISABLED_COLOR = "#bbbbbb"


def quality_color(kohm: float) -> str:
    if kohm < 20:
        return "#2ca02c"
    if kohm < 50:
        return "#e6b800"
    return "#d62728"


class HeadMap(pg.PlotWidget):
    def __init__(self, status: QLabel) -> None:
        super().__init__(background="w")
        self.status = status
        self.setAspectLocked(True)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setMouseEnabled(False, False)
        self.draw_head()

        self.kohm = np.full(len(NAMES), 10.0)
        self.disabled: set[str] = set()
        self.spots = pg.ScatterPlotItem(pos=list(ELECTRODES.values()), data=NAMES, size=26, pen="k")
        self.spots.sigClicked.connect(self.on_click)
        self.addItem(self.spots)
        for name, position in ELECTRODES.items():
            label = pg.TextItem(name, color="k", anchor=(0.5, 0.5))
            label.setPos(*position)
            self.addItem(label)
        self.refresh_colors()

    def draw_head(self) -> None:
        pen = pg.mkPen("k", width=2)
        angle = np.linspace(0, 2 * np.pi, 200)
        self.plot(np.cos(angle), np.sin(angle), pen=pen)
        self.plot([-0.1, 0, 0.1], [0.99, 1.12, 0.99], pen=pen)  # nose
        ear = np.linspace(-np.pi / 2, np.pi / 2, 30)
        for side in (-1, 1):
            self.plot(side * (1 + 0.06 * np.cos(ear)), 0.15 * np.sin(ear), pen=pen)

    def refresh_colors(self) -> None:
        self.spots.setBrush(
            [
                DISABLED_COLOR if name in self.disabled else quality_color(kohm)
                for name, kohm in zip(NAMES, self.kohm, strict=True)
            ]
        )

    def on_click(self, _item, points, _event) -> None:
        name = points[0].data()
        self.disabled ^= {name}
        state = "disabled" if name in self.disabled else "enabled"
        self.status.setText(f"{name}: {state}, {self.kohm[NAMES.index(name)]:.0f} kOhm")
        self.refresh_colors()


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("08 - Head map")
        self.resize(560, 620)
        status = QLabel("Click an electrode.")
        self.head_map = HeadMap(status)

        layout = QVBoxLayout(self)
        layout.addWidget(self.head_map, 1)
        layout.addWidget(status)

        self.rng = np.random.default_rng()
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self.fake_impedance_step)
        self.timer.start()

    def fake_impedance_step(self) -> None:
        drift = self.rng.normal(0, 6, len(NAMES))
        self.head_map.kohm = np.clip(self.head_map.kohm + drift, 1, 120)
        self.head_map.refresh_colors()


def main() -> None:
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
