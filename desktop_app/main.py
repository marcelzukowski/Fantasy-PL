from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_app.main_window import MainWindow
from desktop_app.project import resolve_project_root
from desktop_app.theme import apply_app_theme


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FPL.ControlCenter.PremierLeague.Desktop"
        )
    except Exception:
        pass


def show_main_window(window: MainWindow) -> None:
    window.showMaximized()


def main() -> int:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("FPL Control Center")
    apply_app_theme(app)
    try:
        window = MainWindow(resolve_project_root())
    except Exception as exc:
        QMessageBox.critical(None, "FPL Control Center", f"Application startup failed.\n\n{exc}")
        return 1
    show_main_window(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
