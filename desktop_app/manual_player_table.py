"""Local model/view player comparison; no scientific or provider imports."""

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)


COLUMNS = (
    ("Name", "name"),
    ("Pos", "position"),
    ("Club", "club"),
    ("Price", "price"),
    ("Points so far", "points_so_far"),
    ("Next GW proj", "next_gw_projection"),
    ("Next 5 GW total", "next_5gw_total"),
    ("Fixtures / projected points (5GW)", "fixtures_5gw"),
)


def fixture_text(fixtures):
    return (
        " · ".join(
            f"GW{f['gameweek']} {f.get('opponent') or '—'} {f.get('venue') or ''} "
            + (f"({f['projected_points']:.1f})" if f.get("projected_points") is not None else "(—)")
            for f in fixtures
        )
        or "—"
    )


class PlayerTableModel(QAbstractTableModel):
    checked_changed = Signal(str, bool)
    limit_reached = Signal()

    def __init__(self, owned, parent=None):
        super().__init__(parent)
        self.owned = owned
        self.records = []
        self.checked_ids = set()

    def set_players(self, rows):
        self.beginResetModel()
        self.records = list(rows)
        self.checked_ids.clear()
        self.endResetModel()

    def set_checked(self, ids):
        if set(ids) == self.checked_ids:
            return
        self.checked_ids = set(ids)
        if self.records:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.records) - 1, len(COLUMNS) - 1)
            )

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = "Sell price" if self.owned and section == 3 else COLUMNS[section][0]
            return {
                "Sell price": "Sell\nprice",
                "Points so far": "Points\nso far",
                "Next GW proj": "Next GW\nproj",
                "Next 5 GW total": "Next 5 GW\ntotal",
            }.get(label, label)

    def value(self, row, column):
        record = self.records[row]
        return (
            record.get("selling_price")
            if self.owned and column == 3
            else record.get(COLUMNS[column][1])
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        record = self.records[index.row()]
        checked = record["player_id"] in self.checked_ids
        value = self.value(index.row(), index.column())
        if role == Qt.ItemDataRole.UserRole:
            return record["player_id"]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 7:
                return fixture_text(value or [])
            if value is None:
                return "—"
            if index.column() == 3:
                return f"£{value / 10:.1f}m"
            return f"{value:.2f}" if index.column() in (5, 6) else str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"{record['name']}\n5-GW projection coverage: {record.get('projection_coverage', 0)}/5. "
                "— means unavailable. Fixture xP is shown only when supplied or identified by a single-fixture GW; "
                "multi-fixture GW totals are not split.\n"
                + fixture_text(record.get("fixtures_5gw", []))
                + "\nGW totals: "
                + " · ".join(
                    f"GW{gw['gameweek']}: "
                    + (
                        f"{gw['projected_points']:.2f}"
                        if gw.get("projected_points") is not None
                        else "—"
                    )
                    for gw in record.get("gameweek_projections", [])
                )
            )
        if checked and role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(QColor("#E8D6ED"))
        if checked and role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(QColor("#35043F"))
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(checked)
            return font
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(
                Qt.AlignmentFlag.AlignVCenter
                | (
                    Qt.AlignmentFlag.AlignRight
                    if 3 <= index.column() <= 6
                    else Qt.AlignmentFlag.AlignLeft
                )
            )

    def flags(self, index):
        return super().flags(index) | (
            Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else Qt.ItemFlag.NoItemFlags
        )

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid() or index.column() != 0:
            return False
        pid = self.records[index.row()]["player_id"]
        checked = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        if checked == (pid in self.checked_ids):
            return False
        if checked and len(self.checked_ids) >= 5:
            self.limit_reached.emit()
            return False
        self.checked_ids.add(pid) if checked else self.checked_ids.discard(pid)
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(COLUMNS) - 1))
        self.checked_changed.emit(pid, checked)
        return True


class PlayerProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query, self.position, self.club = "", "All positions", "All clubs"
        self.max_price, self.selected_only = 300, False

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        p = model.records[row]
        return (
            self.query in p["name"].casefold()
            and (self.position == "All positions" or p["position"] == self.position)
            and (self.club == "All clubs" or p["club"] == self.club)
            and model.value(row, 3) <= self.max_price
            and (not self.selected_only or p["player_id"] in model.checked_ids)
        )

    def lessThan(self, left, right):
        model = self.sourceModel()
        a, b = model.value(left.row(), left.column()), model.value(right.row(), right.column())
        if a is None or b is None:
            if a is not None:
                return self.sortOrder() == Qt.SortOrder.AscendingOrder
            if b is not None:
                return self.sortOrder() == Qt.SortOrder.DescendingOrder
        elif a != b:
            return a.casefold() < b.casefold() if isinstance(a, str) else a < b
        return (
            model.records[left.row()]["name"].casefold()
            < model.records[right.row()]["name"].casefold()
        )


class PlayerSelectionTable(QTableView):
    def toggle(self, index):
        if index.isValid():
            check = self.model().index(index.row(), 0)
            state = self.model().data(check, Qt.ItemDataRole.CheckStateRole)
            self.model().setData(
                check,
                Qt.CheckState.Unchecked
                if state == Qt.CheckState.Checked
                else Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            self.setCurrentIndex(index)
            self.toggle(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)


class PlayerSelectionPanel(QWidget):
    def __init__(self, owned, parent=None):
        super().__init__(parent)
        self.side = "OUT" if owned else "IN"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel(self.side + " players — tick a player or row"), 1)
        self.counter = QLabel(self.side + " selected: 0/5")
        self.counter.setStyleSheet("font-weight: bold; color: #5F1A68;")
        header.addWidget(self.counter)
        layout.addLayout(header)
        first = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search " + self.side + " by name")
        self.search.setAccessibleName("Search " + self.side + " players")
        self.position = QComboBox()
        self.position.addItems(["All positions", "GK", "DEF", "MID", "FWD"])
        self.position.setAccessibleName(self.side + " position filter")
        first.addWidget(self.search, 1)
        first.addWidget(self.position)
        layout.addLayout(first)
        second = QHBoxLayout()
        self.club = QComboBox()
        self.club.addItem("All clubs")
        self.club.setAccessibleName(self.side + " club filter")
        self.max_price = QDoubleSpinBox()
        self.max_price.setRange(0, 30)
        self.max_price.setValue(30)
        self.max_price.setPrefix("Max £")
        self.max_price.setSuffix("m")
        self.max_price.setAccessibleName(self.side + " maximum price")
        self.selected_only = QCheckBox("Selected only")
        self.selected_only.setAccessibleName(self.side + " selected only")
        second.addWidget(self.club, 1)
        second.addWidget(self.max_price)
        second.addWidget(self.selected_only)
        layout.addLayout(second)
        sorting = QHBoxLayout()
        sorting.addWidget(QLabel("Sort by"))
        self.sort_by, self.direction = QComboBox(), QComboBox()
        if owned:
            self.sort_by.addItem("Owned order", -1)
        for i, (label, _) in enumerate(COLUMNS[:7]):
            self.sort_by.addItem("Sell price" if owned and i == 3 else label, i)
        self.sort_by.setAccessibleName(self.side + " sort by")
        self.direction.addItems(["Desc", "Asc"])
        self.direction.setAccessibleName(self.side + " sort direction")
        sorting.addWidget(self.sort_by, 1)
        sorting.addWidget(self.direction)
        layout.addLayout(sorting)
        self.source = PlayerTableModel(owned, self)
        self.proxy = PlayerProxy(self)
        self.proxy.setSourceModel(self.source)
        self.table = PlayerSelectionTable()
        self.table.setObjectName("comparator" + self.side + "Players")
        self.table.setAccessibleName(self.side + " player comparison")
        self.table.setModel(self.proxy)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.setWordWrap(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(64)
        for i, width in enumerate((170, 46, 95, 65, 85, 90, 95, 500)):
            self.table.setColumnWidth(i, width)
        self.table.setColumnHidden(7, owned)
        check = (Path(__file__).resolve().parent / "assets/checkbox_check.svg").as_posix()
        self.table.setStyleSheet(
            "QTableView::indicator { width: 22px; height: 22px; border: 2px solid #5F1A68; border-radius: 3px; background: white; }"
            "QTableView::indicator:unchecked { image: none; }"
            f'QTableView::indicator:checked {{ background: #5F1A68; image: url("{check}"); }}'
        )
        layout.addWidget(self.table, 1)
        for control in (
            self.search.textChanged,
            self.position.currentTextChanged,
            self.club.currentTextChanged,
            self.max_price.valueChanged,
            self.selected_only.toggled,
        ):
            control.connect(self.filter)
        self.sort_by.currentIndexChanged.connect(self.sort)
        self.direction.currentIndexChanged.connect(self.sort)
        self.sort_by.setCurrentIndex(0 if owned else self.sort_by.findData(6))
        self.sort()

    @property
    def checked_ids(self):
        return set(self.source.checked_ids)

    def set_players(self, rows):
        self.source.set_players(rows)
        self.club.blockSignals(True)
        current = self.club.currentText()
        self.club.clear()
        self.club.addItem("All clubs")
        self.club.addItems(sorted({r["club"] for r in rows}))
        self.club.setCurrentText(current)
        self.club.blockSignals(False)
        self.filter()
        self.sort()

    def set_checked(self, ids):
        self.source.set_checked(ids)
        self.counter.setText(f"{self.side} selected: {len(ids)}/5")

    def filter(self, *_):
        self.proxy.query = self.search.text().casefold()
        self.proxy.position, self.proxy.club = self.position.currentText(), self.club.currentText()
        self.proxy.max_price = round(self.max_price.value() * 10)
        self.proxy.selected_only = self.selected_only.isChecked()
        self.proxy.invalidate()

    def sort(self, *_):
        column = self.sort_by.currentData()
        self.direction.setEnabled(column >= 0)
        self.proxy.sort(
            column,
            Qt.SortOrder.AscendingOrder
            if column < 0 or self.direction.currentText() == "Asc"
            else Qt.SortOrder.DescendingOrder,
        )
