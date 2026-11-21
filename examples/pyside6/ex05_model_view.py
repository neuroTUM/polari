# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""Model/view: the experiments list as a sortable, searchable table.

Run: uv run ex05_model_view.py

Shows:
- The model owns the data; the view only asks it "what is in row r, column c?".
- QSortFilterProxyModel adds sorting and search without touching the data.
- data() answers per role: text, sort key, colour, tooltip.

Try: type "p0" in the search box, sort by date, add a row.
"""

import datetime as dt
import sys
from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

Role = Qt.ItemDataRole
COLUMNS = ["Title", "Pilot", "Date", "Tiredness", "Recordings", "Status"]


@dataclass
class Row:
    title: str
    pilot: str
    date: dt.date
    tiredness: int
    recordings: int
    local_only: bool

    def values(self) -> list:
        status = "local only" if self.local_only else "on storage"
        return [self.title, self.pilot, self.date, self.tiredness, self.recordings, status]


class ExperimentTableModel(QAbstractTableModel):
    def __init__(self, rows: list[Row]) -> None:
        super().__init__()
        self.rows = rows

    def rowCount(self, parent=None) -> int:
        return len(self.rows)

    def columnCount(self, parent=None) -> int:
        return len(COLUMNS)

    def data(self, index, role=Role.DisplayRole):
        row = self.rows[index.row()]
        value = row.values()[index.column()]
        match role:
            case Role.DisplayRole:
                return value.strftime("%d-%m-%Y") if isinstance(value, dt.date) else value
            case Role.UserRole:  # sort key: dates as dates, not as "dd-mm-yyyy" text
                return value.toordinal() if isinstance(value, dt.date) else value
            case Role.ForegroundRole if row.local_only:
                return QColor("#888")
        return None

    def headerData(self, section, orientation, role=Role.DisplayRole):
        if role == Role.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def add(self, row: Row) -> None:
        end = len(self.rows)
        self.beginInsertRows(QModelIndex(), end, end)  # tells every view to update
        self.rows.append(row)
        self.endInsertRows()


def sample_rows() -> list[Row]:
    return [
        Row("MI baseline", "p18", dt.date(2026, 6, 9), 3, 4, False),
        Row("SSVEP pilot", "p03", dt.date(2026, 9, 5), 6, 2, False),
        Row("ArrowGame", "p07", dt.date(2026, 4, 29), 2, 6, False),
        Row("c-VEP test", "p21", dt.date(2026, 11, 14), 5, 0, True),
    ]


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("05 - Model/View")
        self.resize(820, 420)

        self.model = ExperimentTableModel(sample_rows())
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Role.UserRole)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # search all columns

        table = QTableView()
        table.setModel(self.proxy)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.doubleClicked.connect(self.on_open)

        search = QLineEdit(placeholderText="Search title, pilot, date...")
        search.textChanged.connect(self.proxy.setFilterFixedString)
        add_button = QPushButton("Add experiment")
        add_button.clicked.connect(self.on_add)
        self.details = QLabel("Double-click a row to open it.")

        top = QHBoxLayout()
        top.addWidget(search, 1)
        top.addWidget(add_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(table, 1)
        layout.addWidget(self.details)

    def on_add(self) -> None:
        n = self.model.rowCount() + 1
        self.model.add(Row(f"New experiment {n}", f"p{n:02d}", dt.date.today(), 0, 0, True))

    def on_open(self, index: QModelIndex) -> None:
        # The view hands out proxy indexes; map back to the real row.
        row = self.model.rows[self.proxy.mapToSource(index).row()]
        self.details.setText(f"Open: {row.title} ({row.pilot}), {row.recordings} recordings")


def main() -> None:
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
