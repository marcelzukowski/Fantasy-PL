from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .fixture_display import FixtureBadgeData, FixtureDisplayRepository
from .kit_assets import KitAssetRepository

DISPLAY_POSITION_ORDER = ("FWD", "MID", "DEF", "GK")
OWNED_POSITION_ORDER = ("GK", "DEF", "MID", "FWD")


@dataclass(frozen=True)
class StrategyLineupPreview:
    starting_xi_ids: tuple[str, ...]
    bench_ids: tuple[str, ...]
    captain_id: str
    vice_captain_id: str
    transfers_out: tuple[str, ...]
    transfers_in: tuple[str, ...]
    action_label: str = "TRANSFER"


class ShirtWidget(QLabel):
    def __init__(self, kit_assets: KitAssetRepository, parent=None):
        super().__init__(parent)
        self._kits = kit_assets
        self.kit_path: str | None = None
        self.setObjectName("ShirtWidget")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(50, 58)

    def set_player(self, player: Any) -> None:
        path = self._kits.path_for(player.team_id, player.provider_id, goalkeeper=player.position == "GK")
        self.kit_path = None if path is None else str(path)
        self.setProperty("kitPath", self.kit_path or "")
        self.setProperty("goalkeeperKit", bool(player.position == "GK" and path is not None))
        if path is None:
            self.clear()
            self.setText("KIT")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.clear()
            self.setText("KIT")
            return
        self.setPixmap(pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class FixtureStrip(QFrame):
    def __init__(self, entries: Iterable[FixtureBadgeData], parent=None):
        super().__init__(parent)
        self.setObjectName("FixtureStrip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        for entry in list(entries)[:3]:
            badge = QLabel(entry.label, self)
            badge.setObjectName("FixtureBadge")
            badge.setProperty("probabilityField", "p_5_plus")
            badge.setProperty("gameweek", entry.gameweek)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setToolTip(entry.tooltip)
            badge.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            badge.setFixedHeight(20)
            percentage = entry.percentage
            if percentage is None:
                colors = ("#F4ECF6", "#37003C")
            elif percentage >= 35:
                colors = ("#37003C", "#FFFFFF")
            elif percentage >= 30:
                colors = ("#6E2A75", "#FFFFFF")
            elif percentage >= 25:
                colors = ("#C7A8CB", "#37003C")
            else:
                colors = ("#F4ECF6", "#37003C")
            badge.setStyleSheet(
                f"QLabel {{background:{colors[0]};color:{colors[1]};border:0;"
                "border-radius:5px;font-size:8px;font-weight:800;padding:1px 3px;}"
            )
            layout.addWidget(badge, 1)


class PlayerCard(QFrame):
    def __init__(self, player: Any, fixture_entries: Iterable[FixtureBadgeData], kit_assets: KitAssetRepository, *, bench=False, bench_number=None, incoming=False, captain=False, vice_captain=False, parent=None):
        super().__init__(parent)
        self.player_id = str(player.player_id)
        self.setObjectName("BenchPlayerCard" if bench else "XIPlayerCard")
        self.setProperty("playerId", self.player_id)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(122 if not bench else 145)
        self.setMaximumWidth(180)
        self.setFixedHeight(108 if bench else 88)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 3, 6, 4)
        root.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.shirt = ShirtWidget(kit_assets, self)
        self.shirt.set_player(player)
        top.addWidget(self.shirt, 0, Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.name = QLabel(player.display_name)
        self.name.setObjectName("PlayerName")
        price = "—" if player.current_price is None else f"£{player.current_price / 10:.1f}"
        prefix = f"B{bench_number} · " if bench_number is not None else ""
        role = " · C" if captain else " · VC" if vice_captain else ""
        self.meta = QLabel(f"{prefix}{player.position} · {price}{role}")
        self.meta.setObjectName("PlayerMeta")
        text.addWidget(self.name)
        text.addWidget(self.meta)
        if incoming:
            marker = QLabel("IN")
            marker.setObjectName("TransferIn")
            text.addWidget(marker)
        text.addStretch(1)
        top.addLayout(text, 1)
        root.addLayout(top, 1)
        root.addWidget(FixtureStrip(fixture_entries, self))


class PitchSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PitchSurface")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.field_background_color = "#187A45"
        self.field_lines_rendered = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self.field_background_color))
        stripe_height = max(1, self.height() // 8)
        for index in range(0, 8, 2):
            painter.fillRect(0, index * stripe_height, self.width(), stripe_height, QColor("#1C8550"))
        line = QPen(QColor(235, 255, 242, 155), 2)
        painter.setPen(line)
        outer = self.rect().adjusted(14, 14, -14, -14)
        painter.drawRoundedRect(outer, 8, 8)
        mid_y = outer.center().y()
        painter.drawLine(outer.left(), mid_y, outer.right(), mid_y)
        painter.drawEllipse(QPointF(outer.center().x(), mid_y), 42, 42)
        box_width = max(100, int(outer.width() * 0.42))
        box_depth = max(42, int(outer.height() * 0.12))
        box_x = outer.center().x() - box_width // 2
        painter.drawRect(box_x, outer.top(), box_width, box_depth)
        painter.drawRect(box_x, outer.bottom() - box_depth, box_width, box_depth)
        painter.setBrush(QColor(255, 255, 255, 125))
        painter.setPen(Qt.PenStyle.NoPen)
        for point in (QPointF(outer.left(), outer.top()), QPointF(outer.right(), outer.top()), QPointF(outer.left(), outer.bottom()), QPointF(outer.right(), outer.bottom())):
            painter.drawEllipse(point, 2.2, 2.2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(line)
        centre_x = outer.center().x()
        painter.drawPolygon(QPolygonF([QPointF(centre_x - 28, outer.top()), QPointF(centre_x + 28, outer.top()), QPointF(centre_x + 22, outer.top() + 8), QPointF(centre_x - 22, outer.top() + 8)]))
        self.field_lines_rendered = True


class BenchPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FPLBenchPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 4, 14, 8)
        root.setSpacing(2)
        title = QLabel("BENCH")
        title.setObjectName("BenchTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        self.card_row = QHBoxLayout()
        self.card_row.setContentsMargins(0, 0, 0, 0)
        self.card_row.setSpacing(16)
        root.addLayout(self.card_row)
        self.setFixedHeight(136)

    def set_cards(self, cards: list[PlayerCard]) -> None:
        while self.card_row.count():
            item = self.card_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.card_row.addStretch(1)
        for card in cards:
            self.card_row.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        self.card_row.addStretch(1)


class SquadPitchWidget(QGroupBox):
    strategyChanged = Signal(str)

    def __init__(self, fixture_repository: FixtureDisplayRepository, parent=None):
        super().__init__("Squad dashboard", parent)
        self.fixture_repository = fixture_repository
        self.kit_assets = KitAssetRepository()
        self._players: dict[str, Any] = {}
        self._owned_ids: list[str] = []
        self._current_xi_ids: list[str] = []
        self._bench_ids: list[str] = []
        self._recommended_xi_ids: list[str] = []
        self._recommended_bench_ids: list[str] = []
        self._recommended_captain_id: str | None = None
        self._recommended_vice_id: str | None = None
        self._transfers_out: list[str] = []
        self._transfers_in: list[str] = []
        self._strategy_previews: dict[str, StrategyLineupPreview] = {}
        self._active_strategy: str | None = None
        self._first_gameweek = 1
        self._showing_recommended = False
        self.setObjectName("SquadDashboard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 9, 8, 8)
        root.setSpacing(8)

        owned_panel = QFrame()
        owned_panel.setObjectName("OwnedPanel")
        owned_panel.setMinimumWidth(300)
        owned_panel.setMaximumWidth(340)
        owned_layout = QVBoxLayout(owned_panel)
        owned_layout.setContentsMargins(8, 5, 8, 6)
        owned_layout.setSpacing(1)
        self.owned_title = QLabel("MY SQUAD · 15")
        self.owned_title.setObjectName("PanelTitle")
        owned_layout.addWidget(self.owned_title)
        columns = QFrame(); columns.setObjectName("OwnedHeader")
        column_layout = QHBoxLayout(columns); column_layout.setContentsMargins(4, 2, 4, 2); column_layout.setSpacing(4)
        for text, width, stretch in (("POS", 28, 0), ("PLAYER", 0, 1), ("PRICE", 38, 0), ("STATUS", 44, 0)):
            label = QLabel(text); label.setObjectName("OwnedColumn")
            if width:
                label.setFixedWidth(width)
            if text in {"PRICE", "STATUS"}:
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(label, stretch)
        owned_layout.addWidget(columns)
        self.owned_rows: list[dict[str, Any]] = []
        for _ in range(15):
            row = QFrame()
            row.setObjectName("OwnedRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 0, 4, 0)
            row_layout.setSpacing(4)
            position = QLabel(); position.setObjectName("OwnedPosition"); position.setFixedWidth(28)
            name = QLabel(); name.setObjectName("OwnedName")
            price = QLabel(); price.setObjectName("OwnedPrice"); price.setAlignment(Qt.AlignmentFlag.AlignRight); price.setFixedWidth(38)
            status = QLabel(); status.setObjectName("OwnedStatus"); status.setAlignment(Qt.AlignmentFlag.AlignCenter); status.setFixedWidth(44)
            row_layout.addWidget(position); row_layout.addWidget(name, 1); row_layout.addWidget(price); row_layout.addWidget(status)
            owned_layout.addWidget(row, 1)
            self.owned_rows.append({"row": row, "position": position, "name": name, "price": price, "status": status})
        root.addWidget(owned_panel)

        centre = QFrame(); centre.setObjectName("XIContainer")
        centre_layout = QVBoxLayout(centre); centre_layout.setContentsMargins(0, 0, 0, 0); centre_layout.setSpacing(3)
        toolbar = QHBoxLayout()
        self.current_button = QPushButton("Current XI"); self.current_button.setObjectName("LineupMode"); self.current_button.setCheckable(True); self.current_button.setChecked(True)
        recommended_label = QLabel("Recommended:"); recommended_label.setObjectName("ModeLabel")
        self.strategic_button = QPushButton("V3 Strategic"); self.strategic_button.setObjectName("LineupMode"); self.strategic_button.setCheckable(True); self.strategic_button.setEnabled(False)
        self.short_term_button = QPushButton("Short-term"); self.short_term_button.setObjectName("LineupMode"); self.short_term_button.setCheckable(True); self.short_term_button.setEnabled(False)
        self.balanced_button = QPushButton("Balanced"); self.balanced_button.setObjectName("LineupMode"); self.balanced_button.setCheckable(True); self.balanced_button.setEnabled(False)
        self.long_term_button = QPushButton("Long-term"); self.long_term_button.setObjectName("LineupMode"); self.long_term_button.setCheckable(True); self.long_term_button.setEnabled(False)
        # Compatibility name for existing desktop tests and integrations.
        self.recommended_button = self.short_term_button
        self._strategy_buttons = {
            "strategic": self.strategic_button,
            "short_term": self.short_term_button,
            "balanced": self.balanced_button,
            "long_term": self.long_term_button,
        }
        self.mode_label = QLabel("Official current lineup"); self.mode_label.setObjectName("ModeLabel")
        toolbar.addWidget(self.current_button); toolbar.addWidget(recommended_label)
        toolbar.addWidget(self.strategic_button); toolbar.addWidget(self.short_term_button); toolbar.addWidget(self.balanced_button); toolbar.addWidget(self.long_term_button)
        toolbar.addStretch(1); toolbar.addWidget(self.mode_label)
        centre_layout.addLayout(toolbar)
        self.current_button.clicked.connect(self._show_current)
        self.strategic_button.clicked.connect(lambda: self._show_strategy("strategic"))
        self.short_term_button.clicked.connect(lambda: self._show_strategy("short_term"))
        self.balanced_button.clicked.connect(lambda: self._show_strategy("balanced"))
        self.long_term_button.clicked.connect(lambda: self._show_strategy("long_term"))
        self.transfer_bar = QFrame(); self.transfer_bar.setObjectName("TransferBar")
        transfer_layout = QHBoxLayout(self.transfer_bar); transfer_layout.setContentsMargins(7, 1, 7, 1)
        self.strategy_label = QLabel(""); self.strategy_label.setObjectName("StrategyLabel")
        self.out_label = QLabel("OUT: —"); self.in_label = QLabel("IN: —")
        transfer_layout.addWidget(self.strategy_label); transfer_layout.addWidget(self.out_label); transfer_layout.addStretch(1); transfer_layout.addWidget(self.in_label)
        centre_layout.addWidget(self.transfer_bar)
        self.pitch = PitchSurface()
        pitch_layout = QVBoxLayout(self.pitch); pitch_layout.setContentsMargins(8, 9, 8, 7); pitch_layout.setSpacing(2)
        self.position_rows: dict[str, tuple[QWidget, QHBoxLayout]] = {}
        for position in DISPLAY_POSITION_ORDER:
            holder = QWidget(); holder.setObjectName(f"{position}Row"); holder.setProperty("pitchRow", True)
            row_layout = QHBoxLayout(holder); row_layout.setContentsMargins(0, 0, 0, 0); row_layout.setSpacing(7)
            pitch_layout.addWidget(holder, 1)
            self.position_rows[position] = (holder, row_layout)
        self.bench_panel = BenchPanel(); pitch_layout.addWidget(self.bench_panel)
        centre_layout.addWidget(self.pitch, 1)
        root.addWidget(centre, 1)

    def refresh(self, player_boxes, players, *, state=None, first_gameweek=None) -> None:
        self._players = players
        self._first_gameweek = int(first_gameweek or self._first_gameweek)
        selected = []
        for position in OWNED_POSITION_ORDER:
            for key, combo in sorted(player_boxes.items()):
                if key[0] == position and combo.currentData() is not None:
                    selected.append(str(combo.currentData()))
        if state is not None and len(state.player_ids) == 15:
            selected = list(state.player_ids)
        self._owned_ids = selected
        self._current_xi_ids = list(state.starting_player_ids) if state is not None and len(state.starting_player_ids) == 11 else self._fallback_xi(selected)
        if state is not None and len(state.bench_player_ids) == 4:
            self._bench_ids = list(state.bench_player_ids)
        else:
            xi = set(self._current_xi_ids)
            self._bench_ids = [value for value in selected if value not in xi]
        self._draw(); self._refresh_owned(); self._refresh_transfers()

    def _fallback_xi(self, owned_ids: list[str]) -> list[str]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for player_id in owned_ids:
            player = self._players.get(player_id)
            if player is not None:
                grouped[player.position].append(player_id)
        wanted = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
        return [pid for position in OWNED_POSITION_ORDER for pid in grouped[position][:wanted[position]]][:11]

    @staticmethod
    def _clear_row(layout: QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None); widget.deleteLater()

    def _card(self, player_id: str, *, bench=False, bench_number=None) -> PlayerCard | None:
        player = self._players.get(str(player_id))
        if player is None:
            return None
        recommended = self._showing_recommended
        return PlayerCard(player, self.fixture_repository.entries_for(player, self._first_gameweek), self.kit_assets, bench=bench, bench_number=bench_number, incoming=recommended and player_id in self._transfers_in, captain=recommended and player_id==self._recommended_captain_id, vice_captain=recommended and player_id==self._recommended_vice_id)

    def _draw(self) -> None:
        ids = self._recommended_xi_ids if self._showing_recommended else self._current_xi_ids
        bench_ids = self._recommended_bench_ids if self._showing_recommended else self._bench_ids
        grouped: dict[str, list[str]] = defaultdict(list)
        for player_id in ids:
            player = self._players.get(player_id)
            if player is not None:
                grouped[player.position].append(player_id)
        for position, (_, layout) in self.position_rows.items():
            self._clear_row(layout); layout.addStretch(1)
            for player_id in grouped[position]:
                card = self._card(player_id)
                if card is not None:
                    layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addStretch(1)
        cards = [card for index, value in enumerate(bench_ids, 1) if (card := self._card(value, bench=True, bench_number=index)) is not None]
        self.bench_panel.set_cards(cards)

    def _refresh_owned(self) -> None:
        xi = set(self._current_xi_ids)
        outgoing = set(self._transfers_out) if self._showing_recommended else set()
        self.owned_title.setText(f"MY SQUAD · {len(self._owned_ids)}")
        for index, row in enumerate(self.owned_rows):
            if index >= len(self._owned_ids):
                for key in ("position", "name", "price", "status"):
                    row[key].setText("")
                continue
            player_id = self._owned_ids[index]; player = self._players.get(player_id)
            if player is None:
                continue
            row["position"].setText(player.position); row["name"].setText(player.display_name)
            row["price"].setText("" if player.current_price is None else f"£{player.current_price / 10:.1f}")
            status = "out" if player_id in outgoing else "xi" if player_id in xi else "bench"
            row["status"].setText(status.upper())
            row["status"].setProperty("status", status)
            row["status"].style().unpolish(row["status"]); row["status"].style().polish(row["status"])

    def _refresh_transfers(self) -> None:
        def names(values):
            return ", ".join(self._players[value].display_name for value in values if value in self._players) or "—"
        if self._showing_recommended and self._active_strategy:
            preview = self._strategy_previews.get(self._active_strategy)
            label = self._active_strategy.replace("_", "-").upper()
            self.strategy_label.setText(f"{label} · {preview.action_label.replace('_', ' ')}" if preview else label)
        else:
            self.strategy_label.setText("")
        if not self._showing_recommended:
            self.transfer_bar.hide()
            self.out_label.clear(); self.in_label.clear()
            return
        self.transfer_bar.show()
        self.out_label.setText(f"OUT: {names(self._transfers_out)}"); self.in_label.setText(f"IN: {names(self._transfers_in)}")

    def _show_current(self) -> None:
        self._showing_recommended = False; self.current_button.setChecked(True)
        for button in self._strategy_buttons.values(): button.setChecked(False)
        self.mode_label.setText("Official current lineup"); self._draw()
        self._refresh_transfers(); self._refresh_owned()

    def _show_strategy(self, strategy: str) -> None:
        preview = self._strategy_previews.get(strategy)
        if preview is None:
            self.mode_label.setText("Strategy not available")
            return
        self._active_strategy = strategy
        self._recommended_xi_ids = list(preview.starting_xi_ids)
        self._recommended_bench_ids = list(preview.bench_ids)
        self._recommended_captain_id = preview.captain_id; self._recommended_vice_id = preview.vice_captain_id
        self._transfers_out = list(preview.transfers_out); self._transfers_in = list(preview.transfers_in)
        self._showing_recommended = True; self.current_button.setChecked(False)
        for key, button in self._strategy_buttons.items(): button.setChecked(key == strategy)
        self.mode_label.setText(
            f"Recommended | {strategy.replace('_', '-')} | {preview.action_label.replace('_', ' ')}"
        )
        self._draw(); self._refresh_transfers(); self._refresh_owned(); self.strategyChanged.emit(strategy)

    def _show_recommended(self) -> None:
        if self._active_strategy is not None:
            self._show_strategy(self._active_strategy)
        elif self._strategy_previews:
            self._show_strategy(next(iter(self._strategy_previews)))

    def clear_recommendations(self) -> None:
        self._strategy_previews = {}; self._active_strategy = None
        self._recommended_xi_ids = []; self._recommended_bench_ids = []
        self._recommended_captain_id = None; self._recommended_vice_id = None
        self._transfers_out = []; self._transfers_in = []
        for button in self._strategy_buttons.values():
            button.setChecked(False); button.setEnabled(False); button.setToolTip("Strategy not available")
        if self._showing_recommended:
            self._show_current()
        else:
            self._refresh_transfers(); self._refresh_owned()

    def set_strategy_recommendations(self, previews, *, players=None, fixture_repository=None,
                                     active_strategy="short_term", first_gameweek: int | None = None) -> None:
        if players is not None: self._players = players
        if fixture_repository is not None: self.fixture_repository = fixture_repository
        if first_gameweek is not None: self._first_gameweek = int(first_gameweek)
        self.clear_recommendations()
        self._strategy_previews = {str(key): value for key, value in dict(previews).items()}
        for key, button in self._strategy_buttons.items():
            available = key in self._strategy_previews
            button.setEnabled(available); button.setToolTip("" if available else "Strategy not available")
        self._active_strategy = active_strategy if active_strategy in self._strategy_previews else next(iter(self._strategy_previews), None)
        if self._active_strategy is not None:
            preview = self._strategy_previews[self._active_strategy]
            self._recommended_xi_ids = list(preview.starting_xi_ids)
            self._recommended_bench_ids = list(preview.bench_ids)
            self._recommended_captain_id = preview.captain_id; self._recommended_vice_id = preview.vice_captain_id
            self._transfers_out = list(preview.transfers_out); self._transfers_in = list(preview.transfers_in)
        self._refresh_transfers(); self._refresh_owned()

    def set_recommendation(self, *, starting_xi_ids, bench_ids, captain_id, vice_captain_id, transfers_out, transfers_in, players=None, fixture_repository=None, first_gameweek=None) -> None:
        preview = StrategyLineupPreview(
            tuple(str(value) for value in starting_xi_ids), tuple(str(value) for value in bench_ids),
            str(captain_id), str(vice_captain_id), tuple(str(value) for value in transfers_out),
            tuple(str(value) for value in transfers_in),
            "ROLL FT" if not transfers_out and not transfers_in else "TRANSFER",
        )
        self.set_strategy_recommendations(
            {"short_term": preview}, players=players, fixture_repository=fixture_repository,
            first_gameweek=first_gameweek,
        )
        self._show_strategy("short_term")

    def populated_count(self) -> int:
        return len(self._current_xi_ids)
