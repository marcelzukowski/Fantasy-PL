from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox

from desktop_app.main_window import MainWindow
from desktop_app.stepper_field import StepperField


ROOT = Path(__file__).resolve().parents[1]


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_integer_buttons_bounds_and_signal():
    _app()
    field = StepperField(value=2, minimum=1, maximum=3, step=1)
    changes = []
    field.valueChanged.connect(changes.append)
    field.increment_button.click()
    field.increment_button.click()
    assert field.value() == 3
    assert changes == [3]
    assert not field.increment_button.isEnabled()
    field.decrement_button.click()
    field.decrement_button.click()
    field.decrement_button.click()
    assert field.value() == 1
    assert changes == [3, 2, 1]
    assert not field.decrement_button.isEnabled()


def test_manual_integer_input_and_invalid_text_restore_value():
    _app()
    field = StepperField(value=5, minimum=1, maximum=38, step=1)
    changes = []
    field.valueChanged.connect(changes.append)
    field.editor.setText("17")
    field.editor.editingFinished.emit()
    assert field.value() == 17
    assert changes == [17]
    field.editor.setText("not a number")
    field.editor.editingFinished.emit()
    assert field.value() == 17
    assert field.editor.text() == "17"


def test_decimal_parser_formatter_and_step():
    _app()
    parser = lambda text: float(text.strip().removeprefix("£").removesuffix("m"))
    formatter = lambda value: f"£{float(value):.1f}m"
    field = StepperField(
        value=0.1,
        minimum=0.0,
        maximum=0.2,
        step=0.1,
        parser=parser,
        formatter=formatter,
        prefix="£",
        suffix="m",
    )
    field.increment_button.click()
    field.increment_button.click()
    assert field.value() == 0.2
    assert field.editor.text() == "£0.2m"
    field.editor.setText("£0.0m")
    field.editor.editingFinished.emit()
    assert field.value() == 0.0
    assert field.prefix() == "£" and field.suffix() == "m"


def test_main_window_uses_only_stepper_fields_for_numeric_controls():
    _app()
    window = MainWindow(ROOT)
    try:
        assert all(
            isinstance(field, StepperField)
            for field in (window.gw_spin, window.ft_spin, window.bank_spin, window.simulation_spin, window.seed_spin)
        )
        assert window.findChildren(QSpinBox) == []
        assert window.findChildren(QDoubleSpinBox) == []
        assert window.bank_spin.editor.text().startswith("£")
    finally:
        window.close()


def test_engine_simulation_setting_accepts_new_maximum_and_clamps_above_it():
    _app()
    window = MainWindow(ROOT)
    try:
        window.simulation_spin.setValue(50_000)
        assert window.simulation_spin.value() == 50_000
        window.simulation_spin.setValue(50_001)
        assert window.simulation_spin.value() == 50_000
    finally:
        window.close()
