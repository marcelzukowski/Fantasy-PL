"""Offscreen source GUI probe; synthetic display data, no engine/network calls."""
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_manual_comparator_ui import widget, mouse_toggle

HERE = Path(__file__).resolve().parent
app = QApplication.instance() or QApplication([])
assert QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf') >= 0
app.setFont(QFont('Segoe UI', 9))
generator = widget.__wrapped__(HERE/'gui-synthetic-root')
view, state = next(generator)
results = []
try:
    for width,height,font_size in ((1550,820,9),(1280,800,9),(1280,800,14)):
        font = view.font()
        font.setPointSize(font_size)
        view.setFont(font)
        view.resize(width,height)
        app.processEvents()
        name = f'comparator-{width}x{height}-font{font_size}.png'
        assert view.grab().save(str(HERE/name))
        results.append(dict(requested_size=[width,height],actual_size=[view.width(),view.height()],
                            font_points=font_size,screenshot=name,
                            out_table_width=view.out_panel.table.width(),
                            in_table_width=view.in_panel.table.width(),
                            out_horizontal_scroll_max=view.out_panel.table.horizontalScrollBar().maximum(),
                            in_horizontal_scroll_max=view.in_panel.table.horizontalScrollBar().maximum()))
    mouse_toggle(view.out_panel,'p0')
    assert view.out_panel.checked_ids == {'p0'}
    table=view.out_panel.table
    index=view.out_panel.proxy.mapFromSource(view.out_panel.source.index(0,0))
    table.setCurrentIndex(index)
    table.setFocus()
    QTest.keyClick(table,Qt.Key.Key_Space)
    assert not view.out_panel.checked_ids
    result=dict(layouts=results,mouse_select_and_keyboard_deselect='PASS',
                synthetic_data=True,packaged_interaction_run=False)
    (HERE/'gui-probe.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
finally:
    try:
        next(generator)
    except StopIteration:
        pass
