# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop_app/main.py'],
    pathex=['.', 'src'],
    binaries=[],
    datas=[
        ('desktop_app/assets', 'desktop_app/assets'),
        ('desktop_app/styles', 'desktop_app/styles'),
        # The desktop process delegates engine commands to the project's
        # external .venv. Keep the exact Market Shadow source modules in the
        # release archive for provenance without importing the full model
        # stack into the GUI process at startup.
        ('src/fpl_engine/current_market_shadow.py', 'fpl_engine'),
        ('src/fpl_engine/data/market_odds.py', 'fpl_engine/data'),
        ('src/fpl_engine/data/providers/the_odds_api.py', 'fpl_engine/data/providers'),
        ('src/fpl_engine/models/events/market_shadow.py', 'fpl_engine/models/events'),
        ('src/fpl_engine/models/events/market_prior.py', 'fpl_engine/models/events'),
        ('src/fpl_engine/models/events/market_blend.py', 'fpl_engine/models/events'),
    ],
    hiddenimports=[
        'qt_material6',
        'fpl_engine.planning.player_availability_risk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "scipy", "pandas", "sklearn", "matplotlib", "pyarrow",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FPLControlCenter_PL',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['desktop_app/assets/brand/premier_league_logo.ico'],
)
