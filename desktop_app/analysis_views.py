"""Structured, read-only presentation widgets for the Analysis tab."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QPlainTextEdit, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .transfer_plans import HorizonTransferPlan
from .transfer_targets import TransferTarget


def _clear_layout(layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.layout() is not None:
            _clear_layout(item.layout())
        if item.widget() is not None:
            item.widget().deleteLater()


class AnalysisSummary(QPlainTextEdit):
    """Read-only wrapped fallback text for incomplete analysis results."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalysisSummary")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlainText(text)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)


class DetailSummary(QFrame):
    """Turns existing ``Label: value`` summaries into compact, wrapped rows."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailSummary")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(1, 1, 1, 1); self._layout.setSpacing(5)
        self._text = ""
        self.setText(text)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)
        _clear_layout(self._layout)
        lines = [line.strip() for line in self._text.splitlines() if line.strip()]
        if not lines:
            self._layout.addStretch(1)
            return
        for index, line in enumerate(lines):
            if ":" not in line:
                note = QLabel(line); note.setObjectName("DetailNote"); note.setWordWrap(True)
                self._layout.addWidget(note)
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            row = QFrame(); row.setObjectName("DetailHighlight" if index == 0 else "DetailRow")
            layout = QHBoxLayout(row); layout.setContentsMargins(8, 5, 8, 5); layout.setSpacing(8)
            label = QLabel(key); label.setObjectName("DetailKey"); label.setWordWrap(True)
            content = QLabel(value); content.setObjectName("DetailValue")
            content.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); content.setWordWrap(True)
            layout.addWidget(label, 1); layout.addWidget(content, 2)
            self._layout.addWidget(row)
        self._layout.addStretch(1)


class TransferPlanCards(QFrame):
    """Visual comparison of existing, engine-validated transfer plans only."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TransferPlanCards")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(1, 1, 1, 1); self._layout.setSpacing(10)
        self._text = ""
        self.setText(text)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)
        _clear_layout(self._layout)
        placeholder = QLabel(self._text)
        placeholder.setObjectName("TransferPlanPlaceholder")
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(placeholder, 1)

    @staticmethod
    def _money(value: int | None) -> str:
        return "—" if value is None else f"£{value / 10:.1f}m"

    @staticmethod
    def _metric(value: float | None, *, signed: bool = False) -> str:
        return "—" if value is None else (f"{value:+.2f}" if signed else f"{value:.2f}")

    @staticmethod
    def _player_names(ids: tuple[str, ...], metadata: Mapping[str, object]) -> str:
        result = []
        for player_id in ids:
            row = metadata.get(player_id, {})
            result.append(str(row.get("name", player_id)) if isinstance(row, Mapping) else str(player_id))
        return ", ".join(result) if result else "—"

    @staticmethod
    def _field(layout: QGridLayout, row: int, label: str, value: str) -> None:
        key = QLabel(label); key.setObjectName("PlanMetricKey")
        data = QLabel(value); data.setObjectName("PlanMetricValue")
        data.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(key, row, 0); layout.addWidget(data, row, 1)

    def render_plans(
        self,
        plans: Iterable[HorizonTransferPlan],
        *,
        metadata: Mapping[str, object],
        selling_prices: Mapping[str, int],
        text: str,
    ) -> None:
        rows = tuple(plans)
        if not rows:
            self.setText(text)
            return
        self._text = str(text)
        _clear_layout(self._layout)
        for index, display_plan in enumerate(rows, 1):
            plan = display_plan.plan
            card = QFrame(); card.setObjectName("TransferPlanPrimary" if index == 1 else "TransferPlanSecondary")
            card.setMinimumWidth(245)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout = QVBoxLayout(card); layout.setContentsMargins(12, 11, 12, 10); layout.setSpacing(7)
            title = QLabel(f"Plan {index} | {display_plan.title}")
            title.setObjectName("PlanTitle"); title.setWordWrap(True); layout.addWidget(title)
            source = QLabel(f"{display_plan.horizon_label} | {plan.source}")
            source.setObjectName("PlanSource"); layout.addWidget(source)
            if plan.roll_free_transfer:
                action = QLabel("ROLL FREE TRANSFER"); action.setObjectName("PlanRoll"); layout.addWidget(action)
            else:
                transfer_grid = QGridLayout(); transfer_grid.setHorizontalSpacing(8); transfer_grid.setVerticalSpacing(5)
                out_label = QLabel("OUT"); out_label.setObjectName("PlanTransferLabel")
                out_value = QLabel(self._player_names(plan.transfers_out, metadata)); out_value.setObjectName("PlanTransferOut"); out_value.setWordWrap(True)
                in_label = QLabel("IN"); in_label.setObjectName("PlanTransferLabel")
                in_value = QLabel(self._player_names(plan.transfers_in, metadata)); in_value.setObjectName("PlanTransferIn"); in_value.setWordWrap(True)
                transfer_grid.addWidget(out_label, 0, 0); transfer_grid.addWidget(out_value, 0, 1)
                transfer_grid.addWidget(in_label, 1, 0); transfer_grid.addWidget(in_value, 1, 1)
                transfer_grid.setColumnStretch(1, 1); layout.addLayout(transfer_grid)
            stats = QFrame(); stats.setObjectName("PlanStats")
            stats_layout = QGridLayout(stats); stats_layout.setContentsMargins(8, 7, 8, 7); stats_layout.setHorizontalSpacing(8); stats_layout.setVerticalSpacing(5)
            self._field(stats_layout, 0, "Transfers", str(plan.transfer_count))
            self._field(stats_layout, 1, "FT used", "—" if plan.free_transfers_used is None else str(plan.free_transfers_used))
            self._field(stats_layout, 2, "Hit", "—" if plan.hit_cost is None else f"{plan.hit_cost} pts")
            self._field(stats_layout, 3, "Bank after", self._money(plan.resulting_bank))
            layout.addWidget(stats)
            gain = QFrame(); gain.setObjectName("PlanGain")
            gain_layout = QGridLayout(gain); gain_layout.setContentsMargins(8, 7, 8, 7); gain_layout.setHorizontalSpacing(8); gain_layout.setVerticalSpacing(4)
            gain_label = QLabel("Selected horizon impact"); gain_label.setObjectName("PlanGainLabel")
            gain_value = QLabel(self._metric(display_plan.impact, signed=True)); gain_value.setObjectName("PlanGainValue")
            gain_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            gain_layout.addWidget(gain_label, 0, 0); gain_layout.addWidget(gain_value, 0, 1)
            self._field(gain_layout, 1, "Impact 1GW", self._metric(plan.impact_1gw, signed=True))
            self._field(gain_layout, 2, "Impact 3GW", self._metric(plan.impact_3gw, signed=True))
            self._field(gain_layout, 3, "Impact 6GW", self._metric(plan.impact_6gw, signed=True))
            layout.addWidget(gain)
            if plan.transfer_count > 1:
                sale_total = sum(selling_prices.get(player_id, 0) for player_id in plan.transfers_out)
                buy_total = sum(row.get("current_price", 0) for player_id in plan.transfers_in if isinstance((row := metadata.get(player_id, {})), Mapping))
                if sale_total > buy_total:
                    funding = QLabel(f"Funding released: {self._money(sale_total - buy_total)}")
                    funding.setObjectName("PlanFootnote"); layout.addWidget(funding)
            layout.addStretch(1)
            self._layout.addWidget(card, 1)


class TransferTargetsTable(QTableWidget):
    """Structured, read-only view of ranked production-bundle targets."""

    _columns = (
        ("#", "rank"), ("Player", "player"), ("Pos", "position"), ("Club", "club"),
        ("Price", "price"), ("Fixtures (6GW)", "fixtures"), ("GW pts", "gw"),
        ("p_5_plus", "p5"), ("Min", "minutes"), ("3GW", "three"),
        ("6GW", "six"), ("Status", "status"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TransferTargets")
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.setAlternatingRowColors(True); self.setWordWrap(False)
        self._reset_columns()

    def _reset_columns(self) -> None:
        self.clearSpans(); self.setColumnCount(len(self._columns))
        self.setHorizontalHeaderLabels([label for label, _key in self._columns])
        header = self.horizontalHeader()
        for index, (_label, key) in enumerate(self._columns):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch if key == "fixtures" else QHeaderView.ResizeMode.ResizeToContents)

    @staticmethod
    def _value(number: float | None, suffix: str = "") -> str:
        return "—" if number is None else f"{number:.2f}{suffix}"

    @staticmethod
    def _price(value: int | None) -> str:
        return "—" if value is None else f"£{value / 10:.1f}m"

    def render_targets(self, targets: Iterable[TransferTarget], *, selected_in_ids: Iterable[str] = (), status_by_id: dict[str, str] | None = None) -> None:
        self._reset_columns()
        selected = {str(player_id) for player_id in selected_in_ids}; rows = tuple(targets)
        self.setRowCount(len(rows))
        for row_index, target in enumerate(rows, 1):
            status = (status_by_id or {}).get(target.player_id, "—")
            values = (
                str(row_index), target.player + ("  IN" if target.player_id in selected else ""),
                target.position, target.club, self._price(target.price_tenths),
                " | ".join(target.fixtures) if target.fixtures else target.next_fixture or "—",
                self._value(target.gameweek_expected_points),
                "—" if target.p_5_plus is None else f"{target.p_5_plus * 100:.0f}%",
                self._value(target.expected_minutes, "m"), self._value(target.ev_next_3),
                self._value(target.ev_next_6), status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if column in {0, 4, 6, 7, 8, 9, 10} else Qt.AlignmentFlag.AlignLeft))
                if column == 11:
                    item.setData(Qt.ItemDataRole.UserRole, status)
                self.setItem(row_index - 1, column, item)
            self.setRowHeight(row_index - 1, 32)
        self._fit_to_rows()

    def setPlainText(self, text: str) -> None:
        self._reset_columns(); self.setRowCount(1); self.setSpan(0, 0, 1, len(self._columns))
        self.setItem(0, 0, QTableWidgetItem(text)); self.setRowHeight(0, 36)
        self._fit_to_rows()

    def _fit_to_rows(self) -> None:
        """Let the outer Analysis page own scrolling, never this table."""
        header_height = max(self.horizontalHeader().height(), self.horizontalHeader().sizeHint().height())
        rows_height = sum(self.rowHeight(row) for row in range(self.rowCount()))
        self.setFixedHeight(header_height + rows_height + self.frameWidth() * 2)

    def toPlainText(self) -> str:
        lines: list[str] = []
        for row in range(self.rowCount()):
            values = [self.item(row, column).text() for column in range(self.columnCount()) if self.item(row, column) is not None]
            if values:
                lines.append(" | ".join(values))
        return "\n".join(lines)
