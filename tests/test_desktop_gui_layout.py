from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QScrollArea

from desktop_app.main import show_main_window
from desktop_app.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_XI = [
    "Calvert-Lewin", "Haaland",
    "Groß", "Tavernier", "B.Fernandes", "Szoboszlai", "Palmer",
    "Maatsen", "Justin", "De Cuyper", "Sels",
]
EXPECTED_BENCH = ["Kelleher", "Evanilson", "Egan", "Giles"]


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _name(card: QFrame) -> str:
    return card.findChild(QLabel, "PlayerName").text()


def _window(width: int, height: int) -> MainWindow:
    app = _app()
    window = MainWindow(ROOT)
    window.resize(width, height)
    window.show()
    app.processEvents()
    return window


def test_main_entrypoint_requests_maximized_window():
    class FakeWindow:
        called = False
        def showMaximized(self):
            self.called = True

    window = FakeWindow()
    show_main_window(window)
    assert window.called


def test_official_lineup_badges_and_goalkeeper_kits():
    window = _window(1600, 900)
    try:
        xi = window.findChildren(QFrame, "XIPlayerCard")
        bench = window.findChildren(QFrame, "BenchPlayerCard")
        state = window._current_state
        assert state is not None
        expected_xi = [
            window.players[player_id].display_name
            for position in ("FWD", "MID", "DEF", "GK")
            for player_id in state.starting_player_ids
            if window.players[player_id].position == position
        ]
        assert [_name(card) for card in xi] == expected_xi
        assert [_name(card) for card in bench] == [window.players[player_id].display_name for player_id in state.bench_player_ids]
        assert sum(len(card.findChildren(QLabel, "FixtureBadge")) for card in xi) == 33
        assert sum(len(card.findChildren(QLabel, "FixtureBadge")) for card in bench) == 12

        first_badges = [card.findChild(QLabel, "FixtureBadge") for card in xi + bench]
        assert all(badge is not None and badge.property("probabilityField") == "p_5_plus" for badge in first_badges)
        assert all("Chance of 5+ FPL points" in badge.toolTip() for badge in first_badges)

        goalkeeper_cards = [
            card for card in xi + bench
            if window.players[next(player_id for player_id, player in window.players.items() if player.display_name == _name(card))].position == "GK"
        ]
        assert len(goalkeeper_cards) == 2
        for card in goalkeeper_cards:
            shirt = card.findChild(QLabel, "ShirtWidget")
            assert shirt.property("goalkeeperKit") is True
            assert "gk_team_" in shirt.property("kitPath")
        assert window.bank_spin.prefix() == "£"
        assert window.season_box.width() >= window.season_box.fontMetrics().horizontalAdvance("2026/27") + 20
        assert not window.squad_editor_dock.isVisible()
        assert _app().property("fplThemeFoundation") == "qt-material6"
        assert window.tabs.currentIndex() == 0

        bench_meta = [card.findChild(QLabel, "PlayerMeta").text() for card in bench]
        assert [text.split(" · ", 1)[0] for text in bench_meta] == ["B1", "B2", "B3", "B4"]
    finally:
        window.close()


def test_responsive_pitch_geometry_and_centered_bench():
    for width, height in ((1600, 820), (1600, 900), (1900, 1080)):
        window = _window(width, height)
        try:
            pitch = window.pitch_widget.pitch
            cards = window.findChildren(QFrame, "XIPlayerCard") + window.findChildren(QFrame, "BenchPlayerCard")
            for card in cards:
                top_left = card.mapTo(pitch, card.rect().topLeft())
                bottom_right = card.mapTo(pitch, card.rect().bottomRight())
                assert top_left.x() >= 0 and top_left.y() >= 0
                assert bottom_right.x() < pitch.width() and bottom_right.y() < pitch.height()
            for index, first in enumerate(cards):
                for second in cards[index + 1:]:
                    if first.parentWidget() is second.parentWidget():
                        assert not first.geometry().intersects(second.geometry())

            panel = window.pitch_widget.bench_panel
            bench = window.findChildren(QFrame, "BenchPlayerCard")
            left = min(card.mapTo(panel, card.rect().topLeft()).x() for card in bench)
            right = max(card.mapTo(panel, card.rect().bottomRight()).x() for card in bench)
            assert abs((left + right) / 2 - panel.width() / 2) <= 1

            pitch_image = pitch.grab().toImage()
            field = pitch_image.pixelColor(5, 5)
            assert field.green() > field.red()
            assert pitch.field_background_color == "#187A45"
            assert pitch.field_lines_rendered
            assert window.tabs.tabBar().height() >= 34

            window._toggle_squad_editor()
            _app().processEvents()
            drawer = window.edit_squad_drawer
            assert drawer.isVisible()
            assert 360 <= drawer.width() <= 420
            assert drawer.geometry().right() <= window.rect().right()
            assert drawer.geometry().bottom() <= window.rect().bottom()
            scroll = drawer.findChild(QScrollArea, "SquadEditorScroll")
            assert scroll.horizontalScrollBar().maximum() == 0
        finally:
            window.close()


def test_editor_drawer_never_leaks_between_tabs():
    window = _window(1600, 900)
    try:
        assert window.dockWidgetArea(window.squad_editor_dock).name == "RightDockWidgetArea"
        window._toggle_squad_editor()
        _app().processEvents()
        assert window.squad_editor_dock.isVisible()
        assert len(window.player_boxes) == 15
        assert len(window.chip_boxes) == 8

        window.tabs.setCurrentIndex(1)
        _app().processEvents()
        assert not window.edit_squad_drawer.isVisible()

        window.tabs.setCurrentIndex(0)
        _app().processEvents()
        assert not window.edit_squad_drawer.isVisible()

        window._toggle_squad_editor()
        assert window.edit_squad_drawer.isVisible()
        window.tabs.setCurrentIndex(2)
        _app().processEvents()
        assert not window.edit_squad_drawer.isVisible()

        window.tabs.setCurrentIndex(0)
        window._toggle_squad_editor()
        close = window.findChild(QPushButton, "DrawerClose")
        assert close is not None
        close.click()
        _app().processEvents()
        assert not window.edit_squad_drawer.isVisible()
    finally:
        window.close()


def test_bench_outline_and_compact_input_controls_are_project_owned():
    stylesheet = (ROOT / "desktop_app/styles/pl_theme.qss").read_text(encoding="utf-8")
    bench_rule = stylesheet.split("QFrame#FPLBenchPanel", 1)[1].split("}", 1)[0]
    assert "border: 0" in bench_rule
    assert "background: #37003C" in bench_rule
    assert "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal" in stylesheet
    assert "width: 0" in stylesheet
    assert "QScrollBar::handle:vertical:hover" in stylesheet
    assert "QFrame#StepperField" in stylesheet
    assert "QToolButton#StepperButton" in stylesheet
    assert "QSpinBox::up-button" not in stylesheet

    window = _window(1600, 820)
    try:
        panel = window.pitch_widget.bench_panel
        image = panel.grab().toImage()
        centre = image.width() // 2
        assert image.pixelColor(centre, 1) == image.pixelColor(centre, 3)
        bench_cards = window.findChildren(QFrame, "BenchPlayerCard")
        assert len(bench_cards) == 4
        assert sum(len(card.findChildren(QLabel, "FixtureBadge")) for card in bench_cards) == 12
        window.simulation_spin.setValue(10000)
        window.seed_spin.setValue(999999999)
        _app().processEvents()
        assert window.simulation_spin.editor.width() > window.simulation_spin.editor.fontMetrics().horizontalAdvance(window.simulation_spin.editor.text())
        assert window.seed_spin.editor.width() > window.seed_spin.editor.fontMetrics().horizontalAdvance(window.seed_spin.editor.text())
    finally:
        window.close()
