from __future__ import annotations

from collections.abc import Callable
from math import isclose

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QToolButton


Number = int | float


class StepperField(QFrame):
    """Compact numeric editor with explicit decrement and increment buttons."""

    valueChanged = Signal(object)

    def __init__(
        self,
        *,
        value: Number = 0,
        minimum: Number = 0,
        maximum: Number = 100,
        step: Number = 1,
        parser: Callable[[str], Number] | None = None,
        formatter: Callable[[Number], str] | None = None,
        prefix: str = "",
        suffix: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        if maximum < minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        if step <= 0:
            raise ValueError("step must be positive")
        self.setObjectName("StepperField")
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._is_integer = all(isinstance(item, int) and not isinstance(item, bool) for item in (value, minimum, maximum, step))
        self._parser = parser or (lambda text: int(text.strip()) if self._is_integer else float(text.strip()))
        self._prefix = prefix
        self._suffix = suffix
        self._formatter = formatter or self._default_formatter
        self._value: Number = minimum

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.editor = QLineEdit(self)
        self.editor.setObjectName("StepperValue")
        self.editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.decrement_button = QToolButton(self)
        self.decrement_button.setObjectName("StepperButton")
        self.decrement_button.setProperty("stepRole", "decrement")
        self.decrement_button.setText("−")
        self.increment_button = QToolButton(self)
        self.increment_button.setObjectName("StepperButton")
        self.increment_button.setProperty("stepRole", "increment")
        self.increment_button.setText("+")
        self.decrement_button.setToolTip("Decrease")
        self.increment_button.setToolTip("Increase")
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.decrement_button)
        layout.addWidget(self.increment_button)

        self.decrement_button.clicked.connect(lambda: self.setValue(self._value - self._step))
        self.increment_button.clicked.connect(lambda: self.setValue(self._value + self._step))
        self.editor.editingFinished.connect(self._commit_editor)
        self.setValue(value, emit=False)

    def _default_formatter(self, value: Number) -> str:
        rendered = str(int(value)) if self._is_integer else f"{float(value):g}"
        return f"{self._prefix}{rendered}{self._suffix}"

    def _normalize(self, value: Number) -> Number:
        bounded = min(self._maximum, max(self._minimum, value))
        if self._is_integer:
            return int(round(bounded))
        return round(float(bounded), 10)

    def _commit_editor(self) -> None:
        try:
            parsed = self._parser(self.editor.text())
        except (TypeError, ValueError):
            self.editor.setText(self._formatter(self._value))
            return
        self.setValue(parsed)

    def value(self) -> Number:
        return self._value

    def setValue(self, value: Number, *, emit: bool = True) -> None:
        normalized = self._normalize(value)
        changed = not isclose(float(normalized), float(self._value), rel_tol=0.0, abs_tol=1e-10)
        self._value = normalized
        self.editor.setText(self._formatter(normalized))
        self.decrement_button.setEnabled(normalized > self._minimum)
        self.increment_button.setEnabled(normalized < self._maximum)
        if changed and emit:
            self.valueChanged.emit(normalized)

    def setRange(self, minimum: Number, maximum: Number) -> None:
        if maximum < minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        self._minimum, self._maximum = minimum, maximum
        self.setValue(self._value)

    def setSingleStep(self, step: Number) -> None:
        if step <= 0:
            raise ValueError("step must be positive")
        self._step = step

    def prefix(self) -> str:
        return self._prefix

    def suffix(self) -> str:
        return self._suffix
