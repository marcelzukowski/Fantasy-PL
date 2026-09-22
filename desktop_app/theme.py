from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import ModuleType

from PySide6.QtWidgets import QApplication


STYLE_ROOT = Path(__file__).resolve().parent / "styles"
MATERIAL_THEME = STYLE_ROOT / "pl_material.xml"
MATERIAL_TEMPLATE = STYLE_ROOT / "material_foundation.qss"
PL_STYLESHEET = STYLE_ROOT / "pl_theme.qss"


def _load_qt_material6():
    """Load the pinned fork while containing its two broken absolute imports.

    The upstream 0.5.0 wheel imports ``qt_style_tools`` and ``resources`` as
    top-level modules and omits its package data. The application only needs
    its supported stylesheet renderer, so the unused runtime-theme helpers
    and icon generator receive narrow compatibility shims here.
    """
    if "qt_style_tools" not in sys.modules:
        style_tools = ModuleType("qt_style_tools")
        style_tools.QtStyleTools = type("QtStyleTools", (), {})
        sys.modules["qt_style_tools"] = style_tools
    if "resources" not in sys.modules:
        resources = ModuleType("resources")

        class ResourceGenerator:
            def __init__(self, *args, **kwargs):
                self.index = ""

            def generate(self):
                return None

        resources.ResourseGenerator = ResourceGenerator
        sys.modules["resources"] = resources
    return importlib.import_module("qt_material6")


def apply_app_theme(app: QApplication) -> None:
    """Apply the Material foundation and the project-owned PL identity."""
    if app.property("fplThemeApplied"):
        return
    material = _load_qt_material6()
    material.add_fonts = lambda: None
    material.set_icons_theme = lambda *args, **kwargs: None
    foundation = material.build_stylesheet(
        theme=str(MATERIAL_THEME),
        template=str(MATERIAL_TEMPLATE),
        extra={"font_family": "Segoe UI", "density_scale": "0"},
    )
    if not foundation:
        raise RuntimeError("qt-material6 could not build the desktop foundation")
    custom = PL_STYLESHEET.read_text(encoding="utf-8")
    app.setStyleSheet(foundation + "\n" + custom)
    app.setProperty("fplThemeApplied", True)
    app.setProperty("fplThemeFoundation", "qt-material6")
