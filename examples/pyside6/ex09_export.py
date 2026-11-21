# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0", "pyqtgraph==0.14.0", "numpy"]
# ///
"""Export a plot as PNG, SVG and a one-page PDF report.

Run: uv run ex09_export.py

Shows:
- PNG: pyqtgraph's ImageExporter, at any pixel width.
- SVG: Qt's QSvgGenerator records what the widget paints.
  (pyqtgraph's own SVGExporter crashes with Qt 6.12.)
- PDF: QPdfWriter + QPainter, no extra library.

Try: export all three and open the files in ./exports.
"""

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

EXPORT_DIR = Path(__file__).parent / "exports"


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("09 - Export")
        self.resize(900, 560)

        t = np.linspace(0, 60, 600)
        power = 5 + 3 * np.sin(t / 6) + np.random.default_rng(1).normal(0, 0.5, t.size)
        self.plot = pg.PlotWidget(title="Alpha power, channel Oz (synthetic)", background="w")
        self.plot.plot(t, power, pen=pg.mkPen("#1f77b4", width=2))
        self.plot.setLabel("bottom", "time", units="s")
        self.plot.setLabel("left", "power", units="µV²")

        buttons = QHBoxLayout()
        for text, export in [("PNG", self.save_png), ("SVG", self.save_svg), ("PDF report", self.save_pdf)]:
            button = QPushButton(f"Save {text}")
            button.clicked.connect(lambda _=False, export=export: self.on_export(export))
            buttons.addWidget(button)
        self.status = QLabel(f"Files go to {EXPORT_DIR}")

        layout = QVBoxLayout(self)
        layout.addWidget(self.plot, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)

    def on_export(self, export) -> None:
        EXPORT_DIR.mkdir(exist_ok=True)
        path = export(EXPORT_DIR / f"alpha-oz-{dt.datetime.now():%Y%m%d-%H%M%S}")
        self.status.setText(f"Saved {path}")

    def save_png(self, stem: Path) -> Path:
        path = stem.with_suffix(".png")
        exporter = pg.exporters.ImageExporter(self.plot.plotItem)
        exporter.parameters()["width"] = 1600
        exporter.export(str(path))
        return path

    def save_svg(self, stem: Path) -> Path:
        path = stem.with_suffix(".svg")
        generator = QSvgGenerator()
        generator.setFileName(str(path))
        generator.setSize(self.plot.size())
        generator.setViewBox(self.plot.rect())
        painter = QPainter(generator)
        self.plot.render(painter)
        painter.end()
        return path

    def save_pdf(self, stem: Path) -> Path:
        path = stem.with_suffix(".pdf")
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setResolution(150)
        painter = QPainter(writer)
        width = painter.viewport().width()

        painter.setFont(QFont("Helvetica", 18, QFont.Weight.Bold))
        painter.drawText(QRectF(0, 0, width, 60), "Experiment summary")
        painter.setFont(QFont("Helvetica", 11))
        lines = ["Title: MI baseline", "Pilot: p18", f"Exported: {dt.datetime.now():%d-%m-%Y %H:%M}"]
        for i, line in enumerate(lines):
            painter.drawText(QRectF(0, 80 + i * 35, width, 35), line)

        image = self.plot.grab().toImage()
        painter.drawImage(QRectF(0, 220, width, width * image.height() / image.width()), image)
        painter.end()
        return path


def main() -> None:
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
