from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import os
import shutil
import subprocess

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QStatusBar, QTabWidget,
    QVBoxLayout, QWidget,
    QApplication,
)

from .data_access import bootstrap_saved_wc, load_players, resolve_player_source
from .decision_orchestration import (
    DecisionRunState, decision_arguments, decision_bundle_for_state, planning_context_for_state,
    decision_report_path, load_decision_report, write_decision_request,
)
from .chip_orchestration import (
    ChipRunState, chip_arguments, chip_bundle_for_state, chip_report_path,
    format_chip_summary, load_chip_report,
)
from .captaincy import format_captaincy_summary
from .full_analysis import FullAnalysisState, RUNNING_FULL_ANALYSIS_STATES, full_analysis_summary
from .fpl_account import AccountSyncState, account_state_issues, cdp_debug_session_available
from .fixture_display import FixtureDisplayRepository
from .gameweek_deadlines import first_actionable_gameweek, load_cached_event_deadlines
from .recommended_lineup import RecommendedLineupError, build_recommended_lineup
from fpl_engine.reports import ChipReportV2, DecisionReportV2, plan_id
from .run_center import (
    AnalysisRun,
    ProjectionRun,
    RunCenterError,
    discover_analysis_runs,
    discover_projection_runs,
    write_analysis_run,
    verify_analysis_report_references,
)
from .orchestration import DesktopEngineError, latest_prediction_run, projection_arguments, projection_run_summary, resolve_engine_python
from .analysis_views import DetailSummary, TransferPlanCards, TransferTargetsTable
from .transfer_plans import horizon_transfer_plans
from .squad_pitch import SquadPitchWidget, StrategyLineupPreview
from .stepper_field import StepperField
from .state import POSITION_COUNTS, DesktopSquadState, DesktopStateError, load_state, planning_state_changed, preserve_account_state, save_state, validate_state
from .theme import apply_app_theme
from .transfer_targets import (
    TransferTarget,
    TransferTargetError,
    affordability_status,
    filter_transfer_targets,
    load_transfer_targets,
)


class MainWindow(QMainWindow):
    """Stable desktop shell for account state, projections and squad display."""

    def __init__(self, root: Path):
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            apply_app_theme(app)
        self.root = Path(root).resolve()
        self.state_path = self.root / "data" / "user" / "squad_state.json"
        self.player_source = resolve_player_source(self.root)
        self.players = load_players(self.player_source)
        self.fixture_repository = FixtureDisplayRepository(self.player_source)
        self.player_boxes: dict[tuple[str, int], QComboBox] = {}
        self.chip_boxes: dict[str, QCheckBox] = {}
        self.engine_process: QProcess | None = None
        self.decision_process: QProcess | None = None
        self.decision_run_state = DecisionRunState.IDLE
        self._decision_stdout = ""
        self.latest_decision_report: Path | None = None
        self.chip_process: QProcess | None = None
        self.chip_run_state = ChipRunState.IDLE
        self._chip_stdout = ""
        self.latest_chip_report: Path | None = None
        self.full_analysis_state = FullAnalysisState.IDLE
        self._full_analysis_bundle: Path | None = None
        self._chip_cancel_requested = False
        self.account_process: QProcess | None = None
        self.latest_projection_run: Path | None = None
        self._current_state: DesktopSquadState | None = None
        self.account_sync_state = AccountSyncState.DISCONNECTED
        self._cdp_probe = cdp_debug_session_available
        self._login_window_launched = False
        self._transfer_targets: tuple[TransferTarget, ...] = ()
        self._transfer_target_in_ids: tuple[str, ...] = ()
        self._transfer_target_state: DesktopSquadState | None = None
        self._projection_runs: tuple[ProjectionRun, ...] = ()
        self._analysis_runs: tuple[AnalysisRun, ...] = ()
        self.selected_projection_bundle: Path | None = None
        self.selected_analysis_run: AnalysisRun | None = None
        self._active_analysis_run_id: str | None = None
        self._active_analysis_state: DesktopSquadState | None = None
        self._active_horizon_plans = ()
        self._strategy_previews: dict[str, object] = {}
        self._strategy_preview_context: tuple[DesktopSquadState, dict, FixtureDisplayRepository] | None = None

        self.setWindowTitle("FPL Control Center")
        self.setWindowIcon(QIcon(str(self.root / "desktop_app" / "assets" / "brand" / "premier_league_logo.ico")))
        self.resize(1600, 900)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._load_initial_state()
        self._refresh_actionable_gameweek_minimum()
        self.season_box.currentTextChanged.connect(self._refresh_run_center)
        self.gw_spin.valueChanged.connect(self._refresh_run_center)
        self._refresh_run_center()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralRoot")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 8, 10, 7)
        root_layout.setSpacing(6)
        root_layout.addWidget(self._build_header())
        self.tabs = QTabWidget(); self.tabs.setObjectName("MainTabs"); self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.addTab(self._build_squad_tab(), "Squad")
        self.tabs.addTab(self._build_analysis_tab(), "Analysis")
        self.tabs.addTab(self._build_engine_tab(), "Engine")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Players loaded: {len(self.players)} · Ready")
        self._build_editor_dock()

    def _build_header(self) -> QFrame:
        header = QFrame(); header.setObjectName("Header")
        layout = QHBoxLayout(header); layout.setContentsMargins(16, 7, 14, 7); layout.setSpacing(12)
        logo = QLabel(); logo.setObjectName("PremierLeagueLogo"); logo.setFixedSize(54, 50); logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(self.root / "desktop_app" / "assets" / "brand" / "premier_league_logo.svg"))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(52, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo)
        brand = QVBoxLayout(); brand.setSpacing(0)
        title = QLabel("FPL Control Center"); title.setObjectName("Title")
        subtitle = QLabel("Prediction Engine · Desktop"); subtitle.setObjectName("Subtitle")
        brand.addWidget(title); brand.addWidget(subtitle); layout.addLayout(brand); layout.addStretch(1)
        context = QFrame(); context.setObjectName("ContextBar")
        context_layout = QHBoxLayout(context); context_layout.setContentsMargins(7, 3, 7, 3); context_layout.setSpacing(5)
        self.season_box = QComboBox(); self.season_box.addItem("2026/27"); self.season_box.setFixedWidth(112)
        self.gw_spin = StepperField(value=1, minimum=1, maximum=38, step=1); self.gw_spin.setFixedWidth(108)
        self.ft_spin = StepperField(value=0, minimum=0, maximum=5, step=1); self.ft_spin.setFixedWidth(108)
        bank_parser = lambda text: float(text.strip().removeprefix("£").removesuffix("m"))
        bank_formatter = lambda value: f"£{float(value):.1f}m"
        self.bank_spin = StepperField(value=0.0, minimum=0.0, maximum=30.0, step=0.1, parser=bank_parser, formatter=bank_formatter, prefix="£", suffix="m"); self.bank_spin.setFixedWidth(132)
        for text, widget in (("Season", self.season_box), ("GW", self.gw_spin), ("FT", self.ft_spin), ("Bank", self.bank_spin)):
            label = QLabel(text); label.setObjectName("ContextLabel"); context_layout.addWidget(label); context_layout.addWidget(widget)
        layout.addWidget(context)
        account_card = QFrame(); account_card.setObjectName("AccountStatusCard")
        account_layout = QHBoxLayout(account_card); account_layout.setContentsMargins(10, 6, 10, 6)
        self.account_status_label = QLabel("FPL account: checking..."); self.account_status_label.setObjectName("HeaderAccountStatus"); self.account_status_label.setMinimumWidth(230)
        account_layout.addWidget(self.account_status_label)
        layout.addWidget(account_card)
        self.sync_fpl_quick_button = QPushButton("Sync FPL"); self.sync_fpl_quick_button.setObjectName("Primary"); self.sync_fpl_quick_button.clicked.connect(self._account_primary_action)
        layout.addWidget(self.sync_fpl_quick_button)
        return header

    def _build_squad_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(7, 7, 7, 6); layout.setSpacing(4)
        top = QHBoxLayout(); top.addStretch(1)
        self.edit_squad_button = QPushButton("Edit squad"); self.edit_squad_button.setObjectName("Secondary"); self.edit_squad_button.setCheckable(True); self.edit_squad_button.clicked.connect(self._toggle_squad_editor)
        top.addWidget(self.edit_squad_button); layout.addLayout(top)
        self.pitch_widget = SquadPitchWidget(self.fixture_repository, self)
        self.pitch_widget.strategyChanged.connect(self._strategy_changed)
        layout.addWidget(self.pitch_widget, 1)
        return tab

    def _build_editor_widget(self) -> QWidget:
        content = QWidget(); content.setObjectName("SquadEditorContent"); layout = QVBoxLayout(content); layout.setContentsMargins(12, 10, 12, 12); layout.setSpacing(8)
        for position, count in POSITION_COUNTS.items():
            group = QGroupBox({"GK":"Goalkeepers", "DEF":"Defenders", "MID":"Midfielders", "FWD":"Forwards"}[position])
            group_layout = QVBoxLayout(group)
            options = sorted((p for p in self.players.values() if p.position == position), key=lambda p:(p.display_name.casefold(), p.player_id))
            for index in range(count):
                box = QComboBox(); box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); box.setMinimumContentsLength(12); box.addItem("Ă˘â‚¬â€ť select player Ă˘â‚¬â€ť", None)
                for player in options:
                    price = "" if player.current_price is None else f"  £{player.current_price / 10:.1f}"
                    box.addItem(player.display_name + price, player.player_id)
                box.currentIndexChanged.connect(self._refresh_pitch_view)
                self.player_boxes[(position, index)] = box
                group_layout.addWidget(box)
            layout.addWidget(group)
        layout.addStretch(1)
        return content

    def _build_editor_dock(self) -> None:
        self.squad_editor_group = self._build_editor_widget()
        scroll = QScrollArea(); scroll.setObjectName("SquadEditorScroll"); scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); scroll.setWidget(self.squad_editor_group)
        drawer_shell = QWidget(); drawer_shell.setObjectName("DrawerShell")
        drawer_layout = QVBoxLayout(drawer_shell); drawer_layout.setContentsMargins(0, 0, 0, 0); drawer_layout.setSpacing(0); drawer_layout.addWidget(scroll, 1)
        actions = QFrame(); actions.setObjectName("DrawerActions"); buttons = QGridLayout(actions); buttons.setContentsMargins(10, 9, 10, 10); buttons.setSpacing(7)
        validate = QPushButton("Validate"); validate.setObjectName("Secondary"); validate.clicked.connect(self.validate_current_state)
        save = QPushButton("Save state"); save.setObjectName("Primary"); save.clicked.connect(self.save_current_state)
        reset = QPushButton("Reset GW4 WC"); reset.setObjectName("Secondary"); reset.clicked.connect(self.reset_saved_wc)
        close = QPushButton("Close"); close.setObjectName("DrawerClose"); close.clicked.connect(self._close_squad_editor)
        buttons.addWidget(validate,0,0); buttons.addWidget(save,0,1); buttons.addWidget(reset,1,0); buttons.addWidget(close,1,1)
        drawer_layout.addWidget(actions)
        self.edit_squad_drawer = QDockWidget("Edit owned squad", self); self.edit_squad_drawer.setObjectName("SquadEditorDock")
        self.edit_squad_drawer.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea); self.edit_squad_drawer.setWidget(drawer_shell)
        self.edit_squad_drawer.setMinimumWidth(360); self.edit_squad_drawer.setMaximumWidth(420)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.edit_squad_drawer); self.edit_squad_drawer.hide()
        self.resizeDocks([self.edit_squad_drawer], [390], Qt.Orientation.Horizontal)
        self.edit_squad_drawer.visibilityChanged.connect(self.edit_squad_button.setChecked)
        self.squad_editor_dock = self.edit_squad_drawer

    def _build_analysis_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setObjectName("AnalysisScroll"); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(); content.setObjectName("AnalysisContent")
        layout = QVBoxLayout(content); layout.setContentsMargins(12,12,12,10); layout.setSpacing(10)
        self.run_projections = QPushButton("Run new projections"); self.run_projections.setObjectName("Primary"); self.run_projections.clicked.connect(self.start_projection_run)
        self.run_full = QPushButton("Run new analysis"); self.run_full.setObjectName("RunFull"); self.run_full.clicked.connect(self.start_full_analysis)
        run_center = QFrame(); run_center.setObjectName("AnalysisCard")
        center_layout = QGridLayout(run_center); center_layout.setContentsMargins(12, 9, 12, 9); center_layout.setHorizontalSpacing(8); center_layout.setVerticalSpacing(6)
        projection_label = QLabel("Projection run:"); projection_label.setObjectName("AnalysisCardTitle")
        self.projection_run_box = QComboBox(); self.projection_run_box.setObjectName("ProjectionRunSelector")
        self.projection_run_box.currentIndexChanged.connect(self._projection_run_changed)
        self.use_projection_run_button = QPushButton("Use selected"); self.use_projection_run_button.setObjectName("Secondary"); self.use_projection_run_button.clicked.connect(self.use_selected_projection_run)
        self.projection_run_detail = QLabel("No compatible production run selected."); self.projection_run_detail.setObjectName("AnalysisHint")
        self.projection_run_detail.setWordWrap(True)
        center_layout.addWidget(projection_label, 0, 0); center_layout.addWidget(self.projection_run_box, 0, 1)
        center_layout.addWidget(self.use_projection_run_button, 0, 2); center_layout.addWidget(self.run_projections, 0, 3)
        center_layout.addWidget(self.projection_run_detail, 1, 1, 1, 3)
        analysis_label = QLabel("GW Analysis:"); analysis_label.setObjectName("AnalysisCardTitle")
        self.analysis_run_box = QComboBox(); self.analysis_run_box.setObjectName("AnalysisRunSelector")
        self.analysis_run_box.currentIndexChanged.connect(self._analysis_run_changed)
        self.load_analysis_button = QPushButton("Load analysis"); self.load_analysis_button.setObjectName("Secondary"); self.load_analysis_button.clicked.connect(self.load_selected_analysis)
        self.analysis_run_detail = QLabel("No saved compatible analysis."); self.analysis_run_detail.setObjectName("AnalysisHint")
        self.analysis_run_detail.setWordWrap(True)
        center_layout.addWidget(analysis_label, 2, 0); center_layout.addWidget(self.analysis_run_box, 2, 1)
        center_layout.addWidget(self.load_analysis_button, 2, 2); center_layout.addWidget(self.run_full, 2, 3)
        center_layout.addWidget(self.analysis_run_detail, 3, 1, 1, 3)
        action_label = QLabel("Actions:"); action_label.setObjectName("AnalysisHint")
        self.run_decision = QPushButton("Run decision engine"); self.run_decision.clicked.connect(self.start_decision_run)
        self.run_chips = QPushButton("Run chip screen"); self.run_chips.clicked.connect(self.start_chip_run)
        self.cancel_chip_button = QPushButton("Cancel chip analysis"); self.cancel_chip_button.setObjectName("Secondary"); self.cancel_chip_button.clicked.connect(self.cancel_chip_run); self.cancel_chip_button.setEnabled(False)
        self.retry_chip_button = QPushButton("Retry chip analysis"); self.retry_chip_button.setObjectName("Secondary"); self.retry_chip_button.clicked.connect(self.retry_chip_run); self.retry_chip_button.setEnabled(False)
        action_buttons = QWidget(); action_buttons_layout = QHBoxLayout(action_buttons)
        action_buttons_layout.setContentsMargins(0, 0, 0, 0); action_buttons_layout.setSpacing(7)
        for button in (self.run_decision, self.run_chips, self.cancel_chip_button, self.retry_chip_button):
            action_buttons_layout.addWidget(button)
        center_layout.addWidget(action_label, 4, 0)
        center_layout.addWidget(action_buttons, 4, 1, 1, 3)
        center_layout.setColumnStretch(1, 1)
        layout.addWidget(run_center)
        def card(title_text, body):
            frame = QFrame(); frame.setObjectName("AnalysisCard"); box = QVBoxLayout(frame)
            title_label = QLabel(title_text); title_label.setObjectName("AnalysisCardTitle")
            box.addWidget(title_label); box.addWidget(body, 1); return frame, body
        strategic, self.analysis_strategic_summary = card(
            "Strategic Planner V3",
            DetailSummary("V3 will appear after a valid Decision Engine result."),
        )
        strategic.setMinimumHeight(155)
        self.analysis_strategic_card = strategic
        layout.addWidget(strategic)
        results = QHBoxLayout(); results.setSpacing(10)
        transfer, self.analysis_transfer_summary = card(
            "Transfer scenarios",
            TransferPlanCards("No recommendation yet. Run projections first."),
        )
        scenario_note = QLabel(
            "Scenario rankings use projected squad impact. Strategic Action separately accounts for transfer-option value."
        )
        scenario_note.setObjectName("AnalysisHint"); scenario_note.setWordWrap(True)
        transfer.layout().insertWidget(1, scenario_note)
        captain, self.analysis_captain_summary = card(
            "Captaincy",
            DetailSummary("Captain recommendation will appear here."),
        )
        chips, self.analysis_chip_summary = card(
            "Chip strategy",
            DetailSummary("Chip recommendation will appear here."),
        )
        self.analysis_transfer_card = transfer; self.analysis_captain_card = captain; self.analysis_chip_card = chips
        transfer.setMinimumHeight(360)
        captain.setMinimumHeight(205); chips.setMinimumHeight(205)
        side_cards = QVBoxLayout(); side_cards.setSpacing(10); side_cards.addWidget(captain); side_cards.addWidget(chips)
        results.addWidget(transfer, 3); results.addLayout(side_cards, 1); layout.addLayout(results, 2)
        roll, self.analysis_roll_summary = card(
            "If you roll",
            DetailSummary("The V3 roll-now counterfactual will appear after a valid Decision Engine result."),
        )
        roll.setMinimumHeight(160)
        self.analysis_roll_card = roll
        layout.addWidget(roll)
        targets = QFrame(); targets.setObjectName("AnalysisCard")
        targets.setMinimumHeight(280)
        targets_layout = QVBoxLayout(targets); targets_layout.setContentsMargins(12, 10, 12, 10)
        targets_header = QHBoxLayout()
        targets_title = QLabel("Top player targets"); targets_title.setObjectName("AnalysisCardTitle")
        targets_header.addWidget(targets_title); targets_header.addStretch(1)
        self.target_search = QLineEdit(); self.target_search.setObjectName("TargetSearch"); self.target_search.setPlaceholderText("Player or club"); self.target_search.setClearButtonEnabled(True); self.target_search.setMinimumWidth(210)
        self.target_search.textChanged.connect(self._refresh_transfer_targets)
        targets_header.addWidget(self.target_search)
        targets_header.addWidget(QLabel("Position"))
        self.target_position_filter = QComboBox(); self.target_position_filter.setObjectName("TargetPositionFilter")
        for position in ("ALL", "GK", "DEF", "MID", "FWD"):
            self.target_position_filter.addItem(position, position)
        self.target_position_filter.currentIndexChanged.connect(self._refresh_transfer_targets)
        targets_header.addWidget(self.target_position_filter)
        targets_layout.addLayout(targets_header)
        target_metric = QLabel("Informational table ranked by existing weighted 6-GW projected value. Status tests one-transfer affordability only."); target_metric.setObjectName("AnalysisHint")
        targets_layout.addWidget(target_metric)
        self.analysis_targets_summary = TransferTargetsTable()
        self.analysis_targets_summary.setPlainText("Targets appear after a valid Decision Engine result.")
        targets_layout.addWidget(self.analysis_targets_summary, 1)
        layout.addWidget(targets, 1)
        self.analysis_workflow_summary = QLabel(full_analysis_summary(state=self.full_analysis_state)); self.analysis_workflow_summary.setObjectName("AnalysisHint"); self.analysis_workflow_summary.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(self.analysis_workflow_summary)
        scroll.setWidget(content); outer.addWidget(scroll)
        return tab

    def _build_engine_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(12,12,12,10); layout.setSpacing(8)
        top = QHBoxLayout()
        settings = QGroupBox("Projection settings"); settings_layout = QGridLayout(settings)
        self.simulation_spin = StepperField(value=256, minimum=1, maximum=50000, step=64); self.simulation_spin.setMinimumWidth(140)
        self.seed_spin = StepperField(value=42, minimum=0, maximum=999999999, step=1); self.seed_spin.setMinimumWidth(190)
        settings_layout.addWidget(QLabel("Simulations / fixture"),0,0); settings_layout.addWidget(self.simulation_spin,0,1); settings_layout.addWidget(QLabel("Seed"),1,0); settings_layout.addWidget(self.seed_spin,1,1); top.addWidget(settings,1)
        chips_group = QGroupBox("Chips used"); chips_layout = QGridLayout(chips_group)
        names = {"wildcard":"Wildcard", "free_hit":"Free Hit", "bench_boost":"Bench Boost", "triple_captain":"Triple Captain"}
        chips_layout.addWidget(QLabel("First half"),0,0); chips_layout.addWidget(QLabel("Second half"),0,1)
        for row,(chip,name) in enumerate(names.items(),1):
            for column,half in enumerate(("h1","h2")):
                checkbox=QCheckBox(name); self.chip_boxes[f"{chip}_{half}"]=checkbox; chips_layout.addWidget(checkbox,row,column)
        top.addWidget(chips_group,1)
        account = QGroupBox("Account & squad state"); account_layout = QGridLayout(account)
        validate=QPushButton("Validate"); validate.setObjectName("Secondary"); validate.clicked.connect(self.validate_current_state)
        save=QPushButton("Save state"); save.setObjectName("Primary"); save.clicked.connect(self.save_current_state)
        reset=QPushButton("Reset GW4 WC"); reset.setObjectName("Secondary"); reset.clicked.connect(self.reset_saved_wc)
        self.open_fpl_login_button=QPushButton("Open FPL login"); self.open_fpl_login_button.setObjectName("Secondary"); self.open_fpl_login_button.clicked.connect(self.open_fpl_login)
        self.sync_fpl_button=QPushButton("Sync FPL account"); self.sync_fpl_button.setObjectName("Primary"); self.sync_fpl_button.clicked.connect(self.start_account_sync)
        account_layout.addWidget(validate,0,0); account_layout.addWidget(save,0,1); account_layout.addWidget(reset,1,0); account_layout.addWidget(self.open_fpl_login_button,1,1); account_layout.addWidget(self.sync_fpl_button,2,0,1,2); top.addWidget(account,1)
        layout.addLayout(top)
        self.engine_progress=QProgressBar(); self.engine_progress.setRange(0,1); self.engine_progress.setValue(0); self.engine_progress.setTextVisible(False); self.engine_progress.setMaximumHeight(7); layout.addWidget(self.engine_progress)
        log_group=QGroupBox("Engine log"); log_layout=QVBoxLayout(log_group)
        self.engine_log=QPlainTextEdit(); self.engine_log.setReadOnly(True); self.engine_log.setMaximumBlockCount(1000); self.engine_log.setPlaceholderText("Engine output will appear here during runs.")
        log_layout.addWidget(self.engine_log); layout.addWidget(log_group,1); return tab

    def _toggle_squad_editor(self) -> None:
        if self.tabs.currentIndex() != 0:
            self._close_squad_editor()
            return
        self.edit_squad_drawer.setVisible(not self.edit_squad_drawer.isVisible())

    def _close_squad_editor(self) -> None:
        self.edit_squad_drawer.hide()

    def _on_tab_changed(self, index: int) -> None:
        if index != 0:
            self._close_squad_editor()

    @staticmethod
    def _short_simulation_count(value: int) -> str:
        return f"{value // 1000}k" if value % 1000 == 0 else f"{value:,}"

    def _projection_for_id(self, run_id: str | None) -> ProjectionRun | None:
        return next((run for run in self._projection_runs if run.run_id == run_id), None)

    def _refresh_run_center(self, *_args, selected_projection_run_id: str | None = None,
                            selected_analysis_run_id: str | None = None) -> None:
        """Discover local canonical records only; this method never starts a pipeline."""
        if not hasattr(self, "projection_run_box"):
            return
        state = self._state_from_ui()
        previous_projection = selected_projection_run_id or (
            self.selected_projection_bundle.parent.name if self.selected_projection_bundle is not None else None
        )
        self._projection_runs = discover_projection_runs(self.root, season=state.season, gameweek=state.gameweek)
        self.projection_run_box.blockSignals(True)
        self.projection_run_box.clear()
        for run in self._projection_runs:
            self.projection_run_box.addItem(run.label, run.run_id)
            self.projection_run_box.setItemData(self.projection_run_box.count() - 1, run.detail, Qt.ItemDataRole.ToolTipRole)
        selected_projection = self._projection_for_id(previous_projection)
        if selected_projection is None and self._projection_runs:
            selected_projection = self._projection_runs[0]
        if selected_projection is not None:
            self.projection_run_box.setCurrentIndex(self.projection_run_box.findData(selected_projection.run_id))
            self.selected_projection_bundle = selected_projection.bundle_path
            self.latest_projection_run = selected_projection.run_dir
            self.projection_run_detail.setText(selected_projection.detail)
            self.use_projection_run_button.setEnabled(True)
        else:
            self.selected_projection_bundle = None
            self.projection_run_detail.setText("No compatible canonical production run for the selected season and GW.")
            self.use_projection_run_button.setEnabled(False)
        self.projection_run_box.blockSignals(False)

        self._analysis_runs = discover_analysis_runs(self.root, season=state.season, gameweek=state.gameweek)
        selected_run_id = selected_projection.run_id if selected_projection is not None else None
        compatible = tuple(run for run in self._analysis_runs if run.projection_run_id == selected_run_id)
        previous_analysis = selected_analysis_run_id or (
            self.selected_analysis_run.analysis_run_id if self.selected_analysis_run is not None else None
        )
        selected_analysis = next((run for run in compatible if run.analysis_run_id == previous_analysis), None)
        if selected_analysis is None:
            selected_analysis = next((run for run in compatible if run.status in {"COMPLETE", "PARTIAL"}), None)
        self.analysis_run_box.blockSignals(True)
        self.analysis_run_box.clear()
        for run in compatible:
            label = run.label
            projection = self._projection_for_id(run.projection_run_id)
            if projection is not None:
                label += f" · {self._short_simulation_count(projection.simulation_count)}"
            self.analysis_run_box.addItem(label, run.analysis_run_id)
        if selected_analysis is not None:
            self.analysis_run_box.setCurrentIndex(self.analysis_run_box.findData(selected_analysis.analysis_run_id))
            self.selected_analysis_run = selected_analysis
            self.analysis_run_detail.setText(f"Analysis status: {selected_analysis.status} · projection {selected_analysis.projection_run_id}")
            self.load_analysis_button.setEnabled(selected_analysis.status in {"COMPLETE", "PARTIAL"})
        else:
            self.selected_analysis_run = None
            self.analysis_run_detail.setText("No saved COMPLETE or PARTIAL analysis for the selected projection run.")
            self.load_analysis_button.setEnabled(False)
        self.analysis_run_box.blockSignals(False)

    def _projection_run_changed(self, _index: int) -> None:
        self._clear_strategy_previews()
        run = self._projection_for_id(self.projection_run_box.currentData())
        if run is None:
            return
        self.selected_projection_bundle = run.bundle_path
        self.latest_projection_run = run.run_dir
        self.projection_run_detail.setText(run.detail)
        self._refresh_analysis_selector()

    def _refresh_analysis_selector(self) -> None:
        state = self._state_from_ui()
        selected_run_id = self.selected_projection_bundle.parent.name if self.selected_projection_bundle is not None else None
        compatible = tuple(run for run in self._analysis_runs if run.projection_run_id == selected_run_id)
        self.analysis_run_box.blockSignals(True)
        self.analysis_run_box.clear()
        for run in compatible:
            projection = self._projection_for_id(run.projection_run_id)
            sims = f" · {self._short_simulation_count(projection.simulation_count)}" if projection is not None else ""
            self.analysis_run_box.addItem(run.label + sims, run.analysis_run_id)
        selected = next((run for run in compatible if run.status in {"COMPLETE", "PARTIAL"}), None)
        self.selected_analysis_run = selected
        if selected is not None:
            self.analysis_run_box.setCurrentIndex(self.analysis_run_box.findData(selected.analysis_run_id))
            self.analysis_run_detail.setText(f"Analysis status: {selected.status} · projection {selected.projection_run_id}")
            self.load_analysis_button.setEnabled(True)
        else:
            self.analysis_run_detail.setText("No saved COMPLETE or PARTIAL analysis for the selected projection run.")
            self.load_analysis_button.setEnabled(False)
        self.analysis_run_box.blockSignals(False)

    def _analysis_run_changed(self, _index: int) -> None:
        self._clear_strategy_previews()
        selected_id = self.analysis_run_box.currentData()
        run = next((item for item in self._analysis_runs if item.analysis_run_id == selected_id), None)
        self.selected_analysis_run = run
        if run is None:
            return
        compatible = self.selected_projection_bundle is not None and run.projection_run_id == self.selected_projection_bundle.parent.name
        self.analysis_run_detail.setText(
            f"Analysis status: {run.status} · projection {run.projection_run_id}"
            if compatible else "This analysis belongs to a different projection run."
        )
        self.load_analysis_button.setEnabled(compatible and run.status in {"COMPLETE", "PARTIAL"})

    def use_selected_projection_run(self) -> None:
        run = self._projection_for_id(self.projection_run_box.currentData())
        if run is None:
            return
        try:
            state = self._state_from_ui()
            decision_bundle_for_state(self.root, state, run.bundle_path)
        except DesktopEngineError as exc:
            self._append_engine_log(f"RUN CENTER: {exc}")
            self.statusBar().showMessage("The selected production run is no longer compatible.", 10000)
            return
        self.selected_projection_bundle = run.bundle_path
        self._clear_strategy_previews()
        self.latest_projection_run = run.run_dir
        self.projection_run_detail.setText(run.detail)
        self._refresh_analysis_selector()
        self.statusBar().showMessage("Selected production run is active.", 7000)

    def _selected_bundle_for_state(self, state: DesktopSquadState) -> Path:
        if self.selected_projection_bundle is None:
            raise DesktopEngineError("Select a compatible production projection run before continuing.")
        return decision_bundle_for_state(self.root, state, self.selected_projection_bundle)

    def _begin_analysis_history(self, state: DesktopSquadState, bundle: Path) -> None:
        self._clear_strategy_previews()
        self._active_analysis_run_id = "desktop-analysis-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self._active_analysis_state = state
        self._full_analysis_bundle = bundle.parent
        self.latest_decision_report = None
        self.latest_chip_report = None

    def _persist_active_analysis(self, status: str) -> None:
        if self._active_analysis_run_id is None or self._active_analysis_state is None or self._full_analysis_bundle is None:
            return
        try:
            manifest = write_analysis_run(
                self.root,
                analysis_run_id=self._active_analysis_run_id,
                projection_run_id=self._full_analysis_bundle.name,
                state=self._active_analysis_state,
                status=status,
                decision_report=self.latest_decision_report,
                chip_report=self.latest_chip_report,
                recommended_xi_available=self.latest_decision_report is not None,
                captaincy_available=self.latest_decision_report is not None,
            )
        except RunCenterError as exc:
            self._append_engine_log(f"RUN CENTER: could not save analysis history: {exc}")
            return
        self._refresh_run_center(selected_projection_run_id=self._full_analysis_bundle.name,
                                 selected_analysis_run_id=manifest.stem)

    def load_selected_analysis(self) -> None:
        analysis = self.selected_analysis_run
        if analysis is None or self.selected_projection_bundle is None:
            return
        if analysis.projection_run_id != self.selected_projection_bundle.parent.name:
            self.statusBar().showMessage("That analysis belongs to a different projection run.", 10000)
            return
        self._clear_strategy_previews()
        try:
            if analysis.legacy_unverified or analysis.context_id is None:
                raise RunCenterError("Saved analysis is LEGACY / UNVERIFIED. Run a new analysis.")
            if analysis.squad_state is None or analysis.decision_report is None:
                raise RunCenterError("The saved analysis is incomplete.")
            current_state = self._state_from_ui()
            bundle = self._selected_bundle_for_state(current_state)
            current_context = planning_context_for_state(self.root, current_state, bundle)
            if current_context.context_id != analysis.context_id:
                raise RunCenterError("Saved analysis does not match the current planning context.")
            state = analysis.squad_state
            verify_analysis_report_references(self.root, analysis)
            report = load_decision_report(analysis.decision_report)
            if report.context_id != current_context.context_id:
                raise RunCenterError("Saved analysis does not match the current planning context.")
            if report.external_mutations:
                raise RunCenterError("The saved decision report failed the read-only safety check.")
            production_players = load_players(bundle.parent / "current_players.json")
            fixtures = FixtureDisplayRepository(bundle.parent / "current_players.json")
            self._render_transfer_targets(report, state=state, bundle=bundle)
            self._render_transfer_plans(report, state.selling_prices_tenths)
            self._render_strategic_action(report, state)
            self._install_strategy_previews(
                report, state=state, players=production_players, fixtures=fixtures,
            )
            if analysis.chip_report is not None:
                chip_report = load_chip_report(analysis.chip_report)
                if chip_report.context_id != current_context.context_id:
                    raise RunCenterError("Saved analysis does not match the current planning context.")
                if chip_report.external_mutations:
                    raise RunCenterError("The saved chip report failed the read-only safety check.")
                self.analysis_chip_summary.setText(format_chip_summary(chip_report))
                self.latest_chip_report = analysis.chip_report
            else:
                self.analysis_chip_summary.setText("Chip analysis was not completed for this saved partial analysis.")
                self.latest_chip_report = None
        except (DesktopEngineError, RunCenterError) as exc:
            self._append_engine_log(f"RUN CENTER: {exc}")
            self.statusBar().showMessage("Saved analysis could not be loaded safely.", 10000)
            return
        self.latest_decision_report = analysis.decision_report
        self.latest_projection_run = bundle.parent
        self._full_analysis_bundle = bundle.parent
        self._active_analysis_run_id = analysis.analysis_run_id
        self._active_analysis_state = analysis.squad_state
        self._set_full_analysis_state(FullAnalysisState(analysis.status), detail="Saved analysis loaded without recalculation.")
        self.statusBar().showMessage("Saved analysis loaded.", 7000)

    def _state_from_ui(self) -> DesktopSquadState:
        player_ids = [
            str(self.player_boxes[(position, index)].currentData())
            for position, count in POSITION_COUNTS.items()
            for index in range(count)
            if self.player_boxes[(position, index)].currentData() is not None
        ]
        state = DesktopSquadState(
            season=self.season_box.currentText(), gameweek=self.gw_spin.value(), bank_tenths=round(self.bank_spin.value()*10),
            free_transfers=self.ft_spin.value(), player_ids=player_ids,
            chips_used={key: box.isChecked() for key,box in self.chip_boxes.items()}, source=str(self.player_source),
        )
        if self.state_path.exists():
            try:
                previous=load_state(self.state_path); same=set(previous.player_ids)==set(player_ids) and len(player_ids)==15
                state=preserve_account_state(previous,state)
                if same:
                    state.starting_player_ids=list(previous.starting_player_ids); state.bench_player_ids=list(previous.bench_player_ids)
            except DesktopStateError:
                pass
        return state

    def _apply_state(self, state: DesktopSquadState) -> None:
        self._current_state=state
        self._refresh_actionable_gameweek_minimum()
        self.gw_spin.setValue(state.gameweek); self.ft_spin.setValue(state.free_transfers); self.bank_spin.setValue(state.bank_tenths/10)
        for key,checkbox in self.chip_boxes.items(): checkbox.setChecked(bool(state.chips_used.get(key,False)))
        selected={position:[] for position in POSITION_COUNTS}
        for player_id in state.player_ids:
            player=self.players.get(player_id)
            if player is not None: selected[player.position].append(player_id)
        for position,count in POSITION_COUNTS.items():
            for index in range(count):
                box=self.player_boxes[(position,index)]; box.blockSignals(True)
                player_id=selected[position][index] if index < len(selected[position]) else None
                found=box.findData(player_id); box.setCurrentIndex(found if found >= 0 else 0); box.blockSignals(False)
        self._refresh_pitch_view()

    def _load_initial_state(self) -> None:
        try:
            state=load_state(self.state_path) if self.state_path.exists() else bootstrap_saved_wc(self.root)
        except DesktopStateError:
            state=bootstrap_saved_wc(self.root)
        self._apply_state(state); self._refresh_account_status(state)

    def _refresh_actionable_gameweek_minimum(self, *_args) -> None:
        """Clamp live planning to the first cached official deadline not passed.

        This consumes only the local official bootstrap snapshot materialized by
        the pipeline.  It is deliberately invoked after a successful account
        sync too, but never performs an API refresh itself.
        """
        events = load_cached_event_deadlines(self.root)
        minimum = first_actionable_gameweek(events, now=datetime.now(timezone.utc)) if events else None
        if minimum is None:
            return
        maximum = 38
        self.gw_spin.setEnabled(True)
        self.gw_spin.setRange(minimum, maximum)
        if self.gw_spin.value() < minimum:
            self.gw_spin.setValue(minimum)

    def _refresh_pitch_view(self, *args) -> None:
        state = self._state_from_ui() if self.player_boxes else self._current_state
        self.pitch_widget.refresh(self.player_boxes,self.players,state=state,first_gameweek=self.gw_spin.value())

    def _refresh_account_status(self, state=None) -> None:
        if state is None:
            try: state=load_state(self.state_path)
            except DesktopStateError: state=None
        if state is None or state.fpl_entry_id is None:
            self._set_account_sync_state(AccountSyncState.DISCONNECTED); return
        issues = account_state_issues(state, self.players)
        if issues:
            self._append_engine_log("Account completeness gate: FAIL\n" + "\n".join(f"- {issue}" for issue in issues))
            self._set_account_sync_state(AccountSyncState.ERROR, "account data incomplete")
            return
        self._set_account_sync_state(AccountSyncState.CONNECTED, f"prices 15/15 · FT {state.free_transfers}")

    def _set_account_sync_state(self, state: AccountSyncState, detail: str | None = None) -> None:
        self.account_sync_state = state
        label = state.value if detail is None else f"{state.value} · {detail}"
        self.account_status_label.setText(f"FPL account: {label}")
        retry = state in {AccountSyncState.LOGIN_REQUIRED, AccountSyncState.ERROR}
        sync_text = "Retry sync" if retry else "Sync FPL account"
        self.sync_fpl_button.setText(sync_text)
        if state is AccountSyncState.LOGIN_REQUIRED and not self._login_window_launched:
            self.sync_fpl_quick_button.setText("Open FPL login")
        else:
            self.sync_fpl_quick_button.setText("Retry sync" if retry else "Sync FPL")
        syncing = state in {AccountSyncState.CONNECTING, AccountSyncState.SYNCING}
        self.sync_fpl_button.setEnabled(not syncing)
        self.sync_fpl_quick_button.setEnabled(not syncing)

    def _append_engine_log(self, text) -> None:
        if text: self.engine_log.appendPlainText(str(text).rstrip())

    def _read_engine_stdout(self) -> None:
        if self.engine_process is not None:
            self._append_engine_log(bytes(self.engine_process.readAllStandardOutput()).decode("utf-8",errors="replace"))

    def _read_engine_stderr(self) -> None:
        if self.engine_process is not None:
            self._append_engine_log(bytes(self.engine_process.readAllStandardError()).decode("utf-8",errors="replace"))

    def _set_decision_run_state(self, state: DecisionRunState, detail: str | None = None) -> None:
        self.decision_run_state = state
        self.run_decision.setEnabled(state is not DecisionRunState.RUNNING)
        message = "Decision engine" if detail is None else detail
        self.run_decision.setText("Decision engine running..." if state is DecisionRunState.RUNNING else "Run decision engine")
        self.statusBar().showMessage(message, 10000)

    def _read_decision_stdout(self) -> None:
        if self.decision_process is None:
            return
        output = bytes(self.decision_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._decision_stdout += output
        self._append_engine_log(output)

    def _read_decision_stderr(self) -> None:
        if self.decision_process is not None:
            self._append_engine_log(bytes(self.decision_process.readAllStandardError()).decode("utf-8", errors="replace"))

    def _set_chip_run_state(self, state: ChipRunState, detail: str | None = None) -> None:
        self.chip_run_state = state
        self.run_chips.setEnabled(state is not ChipRunState.RUNNING)
        self.run_chips.setText("Chip screen running..." if state is ChipRunState.RUNNING else "Run chip screen")
        self.cancel_chip_button.setEnabled(state is ChipRunState.RUNNING)
        self.retry_chip_button.setEnabled(state in {ChipRunState.ERROR, ChipRunState.CANCELLED} and self.latest_decision_report is not None)
        self.statusBar().showMessage("Chip screen" if detail is None else detail, 10000)

    def _set_full_analysis_state(self, state: FullAnalysisState, *, detail: str | None = None) -> None:
        self.full_analysis_state = state
        current = self._state_from_ui() if self.player_boxes else None
        label = self._full_analysis_bundle.name if self._full_analysis_bundle is not None else None
        self.analysis_workflow_summary.setText(full_analysis_summary(
            state=state, gameweek=current.gameweek if current is not None else None,
            bundle_label=label, chip_status=detail,
        ))
        self.run_full.setEnabled(state not in RUNNING_FULL_ANALYSIS_STATES)
        self.run_full.setText("Full GW analysis running..." if state in RUNNING_FULL_ANALYSIS_STATES else "Run new analysis")
        self.statusBar().showMessage(detail or f"Full GW Analysis: {state.value.replace('_', ' ')}", 10000)

    def start_full_analysis(self) -> None:
        """Run the existing read-only decisions in order, never rebuilding a valid bundle."""
        if self.full_analysis_state in RUNNING_FULL_ANALYSIS_STATES:
            self.statusBar().showMessage("Full GW analysis is already running.", 5000)
            return
        if any(process is not None and process.state() != QProcess.ProcessState.NotRunning for process in (self.engine_process, self.account_process, self.decision_process, self.chip_process)):
            QMessageBox.information(self, "Engine busy", "Wait for the current process to finish.")
            return
        self._set_full_analysis_state(FullAnalysisState.VALIDATING, detail="Validating account state and production bundle...")
        try:
            state = self._state_from_ui()
            validate_state(state, self.players)
            bundle = self._selected_bundle_for_state(state)
            summary = projection_run_summary(bundle.parent)
            if summary.get("season") not in {None, state.season} or summary.get("gameweek") not in {None, state.gameweek}:
                raise DesktopEngineError("The saved production bundle does not match the selected season and GW.")
        except (DesktopStateError, DesktopEngineError) as exc:
            self._append_engine_log(f"FULL GW ANALYSIS: {exc}")
            self._set_full_analysis_state(FullAnalysisState.ERROR, detail="A matching production projection bundle is required.")
            return
        self._begin_analysis_history(state, bundle)
        self.latest_projection_run = bundle.parent
        self._set_full_analysis_state(FullAnalysisState.PROJECTIONS, detail="Reusing matching production projections.")
        self._append_engine_log(f"=== FULL GW ANALYSIS ===\nVALIDATING: PASS\nPROJECTIONS: reused {bundle.parent}")
        self._set_full_analysis_state(FullAnalysisState.DECISION, detail="Running Decision Engine...")
        self.start_decision_run()

    def _full_analysis_after_decision(self, *, succeeded: bool) -> None:
        if self.full_analysis_state not in RUNNING_FULL_ANALYSIS_STATES:
            return
        if not succeeded:
            self._set_full_analysis_state(FullAnalysisState.ERROR, detail="Decision Engine did not complete.")
            self._persist_active_analysis("ERROR")
            return
        self._set_full_analysis_state(FullAnalysisState.RECOMMENDED_XI, detail="Transfer recommendation and Recommended XI are ready.")
        self.analysis_chip_summary.setText("Chip analysis is still calculating. Transfer and Recommended XI results are ready to use.")
        self._set_full_analysis_state(FullAnalysisState.CHIP_SCREEN, detail="Chip Screen is calculating; earlier results remain available.")
        self.start_chip_run()

    def _full_analysis_after_chip(self, *, outcome: str) -> None:
        if self.full_analysis_state is not FullAnalysisState.CHIP_SCREEN:
            return
        if outcome == "success":
            self._set_full_analysis_state(FullAnalysisState.COMPLETE, detail="All read-only analysis stages completed.")
            self._persist_active_analysis("COMPLETE")
        else:
            self._set_full_analysis_state(FullAnalysisState.PARTIAL, detail=f"Decision and Recommended XI are ready; Chip Screen {outcome}.")
            self._persist_active_analysis("PARTIAL")

    def cancel_chip_run(self) -> None:
        if self.chip_process is None or self.chip_process.state() == QProcess.ProcessState.NotRunning:
            return
        self._chip_cancel_requested = True
        self.cancel_chip_button.setEnabled(False)
        self.analysis_chip_summary.setText("Chip analysis cancellation requested. Transfer and Recommended XI remain available.")
        self._append_engine_log("CHIP SCREEN: cancellation requested by user.")
        self.chip_process.terminate()

    def retry_chip_run(self) -> None:
        if self.latest_decision_report is None:
            return
        if self.full_analysis_state is FullAnalysisState.PARTIAL:
            self._set_full_analysis_state(FullAnalysisState.CHIP_SCREEN, detail="Retrying Chip Screen; earlier results remain available.")
        self.start_chip_run()

    def _read_chip_stdout(self) -> None:
        if self.chip_process is not None:
            output = bytes(self.chip_process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._chip_stdout += output
            self._append_engine_log(output)

    def _read_chip_stderr(self) -> None:
        if self.chip_process is not None:
            self._append_engine_log(bytes(self.chip_process.readAllStandardError()).decode("utf-8", errors="replace"))

    @staticmethod
    def _money(value) -> str:
        return "Ă˘â‚¬â€ť" if value is None else f"£{int(value) / 10:.1f}m"

    def _render_decision_result(self, report: DecisionReportV2) -> None:
        selling = self._current_state.selling_prices_tenths if self._current_state else {}
        self._render_transfer_targets(report)
        self._render_transfer_plans(report, selling)
        self._render_strategic_action(report, self._current_state or self._state_from_ui())

    def _clear_transfer_targets(self) -> None:
        self._transfer_targets = ()
        self._transfer_target_in_ids = ()
        self._transfer_target_state = None
        self.analysis_targets_summary.setPlainText("Targets appear after a valid Decision Engine result.")

    def _refresh_transfer_targets(self, *_args) -> None:
        if not self._transfer_targets:
            return
        position = str(self.target_position_filter.currentData() or "ALL")
        rows = filter_transfer_targets(
            self._transfer_targets,
            position=position,
            query=self.target_search.text(),
            limit=10,
        )
        state = self._transfer_target_state
        status_by_id = {}
        if state is not None:
            status_by_id = {
                target.player_id: affordability_status(
                    target,
                    owned_player_ids=state.player_ids,
                    bank_tenths=state.bank_tenths,
                    selling_prices_tenths=state.selling_prices_tenths,
                    players_by_id=self.players,
                )
                for target in rows
            }
        self.analysis_targets_summary.render_targets(
            rows,
            selected_in_ids=self._transfer_target_in_ids,
            status_by_id=status_by_id,
        )

    def _render_transfer_targets(self, report: DecisionReportV2, *, state: DesktopSquadState | None = None,
                                 bundle: Path | None = None) -> None:
        """Render production-bundle alternatives without affecting the decision result."""
        try:
            state = state or self._state_from_ui()
            bundle = bundle or self._selected_bundle_for_state(state)
            self._transfer_targets = load_transfer_targets(
                bundle,
                owned_player_ids=state.player_ids,
                include_owned=True,
            )
            self._transfer_target_state = state
            incoming = report.recommendation.get("transfers_in", ())
            self._transfer_target_in_ids = tuple(str(player_id) for player_id in incoming)
            self._refresh_transfer_targets()
        except (DesktopEngineError, TransferTargetError) as exc:
            self._clear_transfer_targets()
            self.analysis_targets_summary.setPlainText("Top player targets are unavailable for this production bundle.")
            self._append_engine_log(f"TOP PLAYER TARGETS: {exc}")

    def _render_transfer_plans(self, report: DecisionReportV2, selling_prices: dict[str, int]) -> None:
        """Render the existing engine action and its validated V1 portfolio."""
        metadata = report.player_metadata
        plans = horizon_transfer_plans(report.transfer_plan_payload())
        self._active_horizon_plans = plans
        self.analysis_transfer_summary.render_plans(
            plans,
            metadata=metadata,
            selling_prices=selling_prices,
            text=self._format_transfer_plans(report, selling_prices),
        )

    @staticmethod
    def _strategy_key(title: str) -> str:
        return {
            "Best short-term": "short_term",
            "Best balanced": "balanced",
            "Best long-term": "long_term",
        }.get(title, "")

    def _clear_strategy_previews(self) -> None:
        """Remove every preview before changing its source report or run."""
        self._strategy_previews = {}
        self._strategy_preview_context = None
        self._active_horizon_plans = ()
        if hasattr(self, "pitch_widget"):
            self.pitch_widget.clear_recommendations()
        if hasattr(self, "analysis_captain_summary"):
            self._clear_captaincy_result()
        if hasattr(self, "analysis_strategic_summary"):
            self._clear_strategic_action()
        if hasattr(self, "analysis_roll_summary"):
            self.analysis_roll_summary.setText(
                "The V3 roll-now counterfactual will appear after a valid Decision Engine result."
            )

    def _clear_strategic_action(self) -> None:
        self.analysis_strategic_summary.setText(
            "V3 will appear after a valid Decision Engine result."
        )

    def _render_strategic_action(self, report: DecisionReportV2, state: DesktopSquadState) -> None:
        """Render the V3 challenger without substituting V2 utility."""
        strategic = (report.v3_result.to_dict() if report.v3_result is not None else None) if isinstance(report, DecisionReportV2) else report.get("strategic_v3")
        if not isinstance(strategic, dict):
            reason = report.v3_error if isinstance(report, DecisionReportV2) else report.get("strategic_v3_error")
            self.analysis_strategic_summary.setText(
                f"V3 unavailable: {reason}" if isinstance(reason, str) and reason else "V3 unavailable."
            )
            if hasattr(self, "analysis_roll_summary"):
                self.analysis_roll_summary.setText("V3 unavailable.")
            return
        action = strategic.get("current_action")
        hold = strategic.get("hold_now_counterfactual")
        if not isinstance(action, dict) or not isinstance(hold, dict):
            self.analysis_strategic_summary.setText("V3 unavailable: report is incomplete.")
            return
        metadata = report.player_metadata if isinstance(report, DecisionReportV2) else report.get("player_metadata", {})

        def names(values) -> str:
            if not isinstance(values, (list, tuple)):
                return "-"
            return ", ".join(
                str(row.get("name", value)) if isinstance((row := metadata.get(str(value), {})), dict) else str(value)
                for value in values
            ) or "-"

        outgoing = action.get("transfers_out", ())
        incoming = action.get("transfers_in", ())
        if str(action.get("action")) == "HOLD":
            lines = [
                "Recommended now: HOLD / ROLL",
                f"Free transfers: {action.get('free_transfers_before', '-')} -> {action.get('free_transfers_after', '-')} next GW",
                f"Current bank: {self._money(state.bank_tenths)}",
            ]
        else:
            lines = [
                "Recommended now: TRANSFER",
                f"OUT: {names(outgoing)}",
                f"IN: {names(incoming)}",
                f"Transfers used: {action.get('transfers_used', '-')}",
                f"Hit: {action.get('hit_cost_points', '-')} pts",
                f"Bank after: {self._money(action.get('resulting_bank')) if type(action.get('resulting_bank')) is int else '-'}",
                f"Free transfers: {action.get('free_transfers_before', '-')} -> {action.get('free_transfers_after', '-')} next GW",
            ]
        path_points = strategic.get("projected_3gw_path_points")
        terminal = strategic.get("terminal_ft_value")
        delta = strategic.get("delta_vs_hold_now")
        if isinstance(path_points, (int, float)):
            lines.append(f"V3 3-GW path points: {float(path_points):.2f}")
        if isinstance(terminal, (int, float)):
            lines.append(f"Terminal FT value: {float(terminal):.2f}")
        if isinstance(delta, (int, float)):
            lines.append(f"3-GW path advantage vs Roll: {float(delta):+.2f} projected pts")
        lines.append("Next-GW action is indicative and will be recalculated after the next sync.")
        self.analysis_strategic_summary.setText("\n".join(lines))
        self._render_roll_counterfactual(hold, metadata, delta)

    def _render_roll_counterfactual(self, hold: dict, metadata: dict, delta: object) -> None:
        if not hasattr(self, "analysis_roll_summary"):
            return
        path = hold.get("path") if isinstance(hold.get("path"), list) else []
        current = path[0] if path and isinstance(path[0], dict) else {}
        following = path[1] if len(path) > 1 and isinstance(path[1], dict) else {}
        first_later_transfer = next(
            (
                step for step in path[1:]
                if isinstance(step, dict) and step.get("action") == "TRANSFER"
            ),
            None,
        )

        def names(values) -> str:
            if not isinstance(values, (list, tuple)):
                return "-"
            return ", ".join(
                str(row.get("name", value)) if isinstance((row := metadata.get(str(value), {})), dict) else str(value)
                for value in values
            ) or "-"

        risk = following.get("price_risk", {}) if isinstance(following.get("price_risk"), dict) else {}
        lines = [
            "Current GW: HOLD",
            f"FT: {current.get('free_transfers_before', '-')} -> {current.get('free_transfers_after', '-')} next GW",
        ]
        if following.get("action") == "TRANSFER":
            lines.extend((
                f"Projected next-GW action: OUT {names(following.get('transfers_out', ()))}",
                f"IN: {names(following.get('transfers_in', ()))}",
                f"Projected next-GW FT after: {following.get('free_transfers_after', '-')}",
                f"Projected bank after: {self._money(following.get('resulting_bank')) if type(following.get('resulting_bank')) is int else '-'}",
            ))
        else:
            lines.append("Projected next-GW action: HOLD")
            if isinstance(first_later_transfer, dict):
                gameweek = first_later_transfer.get("gw")
                gameweek_label = f"GW{gameweek}" if type(gameweek) is int else "a later GW"
                lines.extend((
                    f"First planned transfer: {gameweek_label}",
                    f"OUT: {names(first_later_transfer.get('transfers_out', ()))}",
                    f"IN: {names(first_later_transfer.get('transfers_in', ()))}",
                    "FT: "
                    f"{first_later_transfer.get('free_transfers_before', '-')} -> "
                    f"{first_later_transfer.get('free_transfers_after', '-')}",
                    "Bank after: "
                    f"{self._money(first_later_transfer.get('resulting_bank')) if type(first_later_transfer.get('resulting_bank')) is int else '-'}",
                ))
            else:
                lines.append("First planned transfer: None within 3-GW horizon")
        lines.append(f"Price risk: {risk.get('level', 'UNAVAILABLE')}")
        if isinstance(risk.get("message"), str):
            lines.append(risk["message"])
        points = hold.get("projected_3gw_path_points")
        if isinstance(points, (int, float)):
            lines.append(f"3-GW V3 result if roll: {float(points):.2f}")
        if isinstance(delta, (int, float)):
            lines.append(f"Difference vs recommended path: {-float(delta):+.2f}")
        self.analysis_roll_summary.setText("\n".join(lines))

    def _render_strategic_v2_diagnostic(self, report: DecisionReportV2, state: DesktopSquadState) -> None:
        """Render existing V2 utility in its own, intentionally separate metric space."""
        action = report.v2_result if isinstance(report, DecisionReportV2) else report.get("strategic_action")
        if not isinstance(action, dict):
            self._clear_strategic_action()
            return
        outgoing = tuple(str(value) for value in action.get("transfers_out", ()))
        incoming = tuple(str(value) for value in action.get("transfers_in", ()))
        metadata = report.player_metadata if isinstance(report, DecisionReportV2) else report.get("player_metadata", {})

        def names(values: tuple[str, ...]) -> str:
            return ", ".join(
                str(row.get("name", player_id)) if isinstance((row := metadata.get(player_id, {})), dict) else player_id
                for player_id in values
            ) or "Ă˘â‚¬â€ť"

        def money(value: object) -> str:
            return self._money(value) if type(value) is int else "Ă˘â‚¬â€ť"

        before = action.get("free_transfers_before")
        after = action.get("free_transfers_after")
        utility = action.get("utility")
        lines = []
        if action.get("action") == "ROLL_FT" or (not outgoing and not incoming):
            lines.extend((
                "Strategic action: ROLL FT",
                "No transfer recommended now.",
                f"Free transfers: {before if type(before) is int else 'Ă˘â‚¬â€ť'} → {after if type(after) is int else 'Ă˘â‚¬â€ť'} next GW",
                f"Current bank: {self._money(state.bank_tenths)}",
                "Reason: Existing Optimizer V2 strategic action retains the transfer option.",
            ))
        else:
            lines.extend((
                "Strategic action: MAKE TRANSFER",
                f"OUT: {names(outgoing)}",
                f"IN: {names(incoming)}",
                f"Transfers used: {action.get('free_transfers_used', 'Ă˘â‚¬â€ť')}",
                f"Hit: {action.get('hit_cost', 'Ă˘â‚¬â€ť')} pts",
                f"Bank after: {money(action.get('resulting_bank'))}",
                f"Free transfers: {before if type(before) is int else 'Ă˘â‚¬â€ť'} → {after if type(after) is int else 'Ă˘â‚¬â€ť'} next GW",
            ))
        if isinstance(utility, (int, float)) and not isinstance(utility, bool):
            lines.append(f"V2 utility: {float(utility):.6f}")
        self.analysis_strategic_summary.setText("\n".join(lines))

    @staticmethod
    def _same_transfers(plan, payload: dict) -> bool:
        """Compare a transfer set, never the incidental provider-list order."""
        return (
            tuple(sorted(str(value) for value in payload.get("transfers_out", ()))) == tuple(sorted(plan.transfers_out))
            and tuple(sorted(str(value) for value in payload.get("transfers_in", ()))) == tuple(sorted(plan.transfers_in))
        )

    @staticmethod
    def _transfer_identity(plan_or_payload) -> dict[str, list[str]]:
        if isinstance(plan_or_payload, dict):
            outgoing = plan_or_payload.get("transfers_out", ())
            incoming = plan_or_payload.get("transfers_in", ())
        else:
            outgoing = plan_or_payload.transfers_out
            incoming = plan_or_payload.transfers_in
        return {
            "transfers_out": sorted(str(value) for value in outgoing),
            "transfers_in": sorted(str(value) for value in incoming),
        }

    @staticmethod
    def _same_plan_identity(plan, serialized_identity: dict) -> bool:
        """Reject a preview from another horizon slot instead of borrowing it."""
        return MainWindow._transfer_identity(plan) == MainWindow._transfer_identity(serialized_identity)

    def _install_strategy_previews(
        self,
        report: DecisionReportV2,
        *,
        state: DesktopSquadState,
        players: dict,
        fixtures: FixtureDisplayRepository,
    ) -> None:
        """Install only typed previews for the exact strategy plan they identify.

        Each preview carries a stable plan_id. This removes the former dependence
        on candidate order or UI card order while preserving the existing
        read-only lineup optimizer output.
        """
        previews: dict[str, StrategyLineupPreview] = {}
        unavailable = report.strategy_unavailable_map
        selected = self._active_horizon_plans or horizon_transfer_plans(report.transfer_plan_payload())
        strategic_action = report.v3_result.current_action if report.v3_result is not None else None
        strategic_preview = report.preview_for("strategic")
        if isinstance(strategic_action, dict) and strategic_preview is not None:
            action_out = tuple(str(value) for value in strategic_action.get("transfers_out", ()))
            action_in = tuple(str(value) for value in strategic_action.get("transfers_in", ()))
            if strategic_preview.plan_id == plan_id(action_out, action_in):
                try:
                    lineup = build_recommended_lineup(state, players, strategic_preview.lineup_payload())
                    previews["strategic"] = StrategyLineupPreview(
                        starting_xi_ids=lineup.starting_xi_ids, bench_ids=lineup.bench_ids,
                        captain_id=lineup.captain_id, vice_captain_id=lineup.vice_captain_id,
                        transfers_out=lineup.transfers_out, transfers_in=lineup.transfers_in,
                        action_label="V3 HOLD" if strategic_action.get("action") == "HOLD" else "V3 TRANSFER",
                    )
                except RecommendedLineupError as exc:
                    self._append_engine_log(f"RECOMMENDED XI Strategic: {exc}")
            else:
                self._append_engine_log("RECOMMENDED XI Strategic: serialized plan identity does not match the strategic action.")
        elif strategic_action is not None:
            reason = unavailable.get("strategic", "matching strategic preview is unavailable")
            self._append_engine_log(f"RECOMMENDED XI Strategic: {reason}")
        elif report.v3_error:
            self._append_engine_log(f"RECOMMENDED XI Strategic: V3 unavailable: {report.v3_error}")
        for display_plan in selected:
            key = self._strategy_key(display_plan.title)
            if not key:
                continue
            preview = report.preview_for(key)
            if preview is None:
                reason = unavailable.get(key, "matching strategy preview is unavailable")
                self._append_engine_log(f"RECOMMENDED XI {display_plan.title}: {reason}")
                continue
            expected_plan_id = plan_id(tuple(display_plan.plan.transfers_out), tuple(display_plan.plan.transfers_in))
            if preview.plan_id != expected_plan_id:
                self._append_engine_log(
                    f"RECOMMENDED XI {display_plan.title}: serialized plan identity does not match the displayed plan."
                )
                continue
            try:
                lineup = build_recommended_lineup(state, players, preview.lineup_payload())
            except RecommendedLineupError as exc:
                self._append_engine_log(f"RECOMMENDED XI {display_plan.title}: {exc}")
                continue
            previews[key] = StrategyLineupPreview(
                starting_xi_ids=lineup.starting_xi_ids,
                bench_ids=lineup.bench_ids,
                captain_id=lineup.captain_id,
                vice_captain_id=lineup.vice_captain_id,
                transfers_out=lineup.transfers_out,
                transfers_in=lineup.transfers_in,
                action_label="ROLL FT" if display_plan.plan.roll_free_transfer else "TRANSFER",
            )
        self._strategy_previews = previews
        self._strategy_preview_context = (state, players, fixtures) if previews else None
        self.pitch_widget.set_strategy_recommendations(
            previews, players=players, fixture_repository=fixtures, active_strategy="strategic",
            first_gameweek=state.gameweek,
        )
        initial = previews.get("strategic") or previews.get("short_term") or next(iter(previews.values()), None)
        if initial is None:
            self._clear_captaincy_result()
            self.statusBar().showMessage("Recommended strategy preview is unavailable for this analysis.", 8000)
            return
        self._render_captaincy_result(
            preview=initial, players=players, fixtures=fixtures,
            recommendation={}, first_gameweek=state.gameweek,
        )

    def _strategy_changed(self, strategy: str) -> None:
        preview = self._strategy_previews.get(strategy)
        context = self._strategy_preview_context
        if preview is None or context is None:
            return
        state, players, fixtures = context
        self._render_captaincy_result(
            preview=preview, players=players, fixtures=fixtures,
            recommendation={}, first_gameweek=state.gameweek,
        )

    def _format_transfer_plans(self, report: DecisionReportV2, selling_prices: dict[str, int]) -> str:
        """Keep a clean, copyable text representation for history and tests."""
        metadata = report.player_metadata

        def name(player_id: str) -> str:
            row = metadata.get(player_id, {})
            return str(row.get("name", player_id)) if isinstance(row, dict) else player_id

        def money(value: int | None) -> str:
            return "Ă˘â‚¬â€ť" if value is None else self._money(value)

        def signed(value: float | None) -> str:
            return "Ă˘â‚¬â€ť" if value is None else f"{value:+.2f}"

        plans = horizon_transfer_plans(report.transfer_plan_payload())
        if not plans:
            return "No valid transfer plan is available from the existing Decision Engine result."
        sections = []
        for index, display_plan in enumerate(plans):
            plan = display_plan.plan
            lines = [f"Plan {index + 1} | {display_plan.title}", f"{display_plan.horizon_label} | {plan.source}"]
            if plan.roll_free_transfer:
                lines.append("ROLL FREE TRANSFER")
            else:
                lines.append("OUT: " + ", ".join(name(player_id) for player_id in plan.transfers_out))
                lines.append("IN: " + ", ".join(name(player_id) for player_id in plan.transfers_in))
            lines.append(
                f"Transfers: {plan.transfer_count} | FT used: "
                f"{plan.free_transfers_used if plan.free_transfers_used is not None else 'Ă˘â‚¬â€ť'} | "
                f"Hit: {plan.hit_cost if plan.hit_cost is not None else 'Ă˘â‚¬â€ť'} pts | "
                f"Bank after: {money(plan.resulting_bank)}"
            )
            lines.append(
                f"Selected horizon impact: {signed(display_plan.impact)} | "
                f"Impact 1GW: {signed(plan.impact_1gw)} | "
                f"3GW: {signed(plan.impact_3gw)} | 6GW: {signed(plan.impact_6gw)}"
            )
            if plan.transfer_count > 1:
                sale_total = sum(selling_prices.get(player_id, 0) for player_id in plan.transfers_out)
                buy_total = sum(
                    row.get("current_price", 0) for player_id in plan.transfers_in
                    if isinstance((row := metadata.get(player_id, {})), dict)
                )
                if sale_total > buy_total:
                    lines.append(f"Funding released: {self._money(sale_total - buy_total)}")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    def _clear_captaincy_result(self) -> None:
        self.analysis_captain_summary.setText("Captain recommendation will appear here.")

    def _render_captaincy_result(self, *, preview, players, fixtures, recommendation: dict,
                                 first_gameweek: int | None = None) -> None:
        self.analysis_captain_summary.setText(format_captaincy_summary(
            preview=preview, players=players, fixtures=fixtures,
            first_gameweek=self._state_from_ui().gameweek if first_gameweek is None else first_gameweek,
            recommendation=recommendation,
        ))

    def start_decision_run(self) -> None:
        if self.decision_process is not None and self.decision_process.state() != QProcess.ProcessState.NotRunning:
            self.statusBar().showMessage("Decision engine is already running.", 5000)
            return
        if any(process is not None and process.state() != QProcess.ProcessState.NotRunning for process in (self.engine_process, self.account_process, self.chip_process)):
            QMessageBox.information(self, "Engine busy", "Wait for the current process to finish.")
            return
        self._clear_captaincy_result()
        self._clear_transfer_targets()
        self._clear_strategy_previews()
        state = self._state_from_ui()
        try:
            validate_state(state, self.players)
            python = resolve_engine_python(self.root)
            bundle = self._selected_bundle_for_state(state)
            request = write_decision_request(self.root / "data" / "interim" / "desktop_decision" / "request.json", state)
            arguments = decision_arguments(
                request_path=request, prediction_bundle=bundle,
                output_dir=self.root / "data" / "processed" / "desktop_decisions" / state.season.replace("/", "-"),
            )
        except (DesktopStateError, DesktopEngineError) as exc:
            self._set_decision_run_state(DecisionRunState.ERROR, "Decision engine needs a matching saved production projection run.")
            self._append_engine_log(f"DECISION ENGINE: {exc}")
            self._full_analysis_after_decision(succeeded=False)
            return
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment(); environment.insert("PYTHONUTF8", "1"); environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment); process.setWorkingDirectory(str(self.root))
        process.readyReadStandardOutput.connect(self._read_decision_stdout); process.readyReadStandardError.connect(self._read_decision_stderr)
        process.finished.connect(self._decision_finished); process.errorOccurred.connect(self._decision_process_error)
        self.decision_process = process; self._decision_stdout = ""; self.engine_progress.setRange(0, 0)
        if self.full_analysis_state is not FullAnalysisState.DECISION:
            self.engine_log.clear()
        self._set_decision_run_state(DecisionRunState.RUNNING, "Decision engine running...")
        self._append_engine_log(f"=== DECISION ENGINE ===\nUsing saved projection bundle: {bundle}\nCommand: {python} {' '.join(arguments)}")
        process.start(str(python), arguments)

    def _decision_process_error(self, error) -> None:
        self._append_engine_log(f"Decision engine QProcess error: {error}")

    def _decision_finished(self, exit_code, exit_status) -> None:
        self._read_decision_stdout(); self._read_decision_stderr(); self.engine_progress.setRange(0, 1); self.engine_progress.setValue(1)
        if int(exit_code) != 0:
            self._append_engine_log(f"DECISION ENGINE: FAILED (exit {exit_code})")
            self._set_decision_run_state(DecisionRunState.ERROR, "Decision engine could not produce a recommendation.")
            self.decision_process = None
            self._full_analysis_after_decision(succeeded=False)
            return
        try:
            report_path = decision_report_path(self._decision_stdout)
            if report_path is None:
                raise DesktopEngineError("Decision report path is missing from engine output.")
            report = load_decision_report(report_path)
            if report.external_mutations:
                raise DesktopEngineError("Decision output failed the read-only safety check.")
        except DesktopEngineError as exc:
            self._append_engine_log(f"DECISION ENGINE: {exc}")
            self._set_decision_run_state(DecisionRunState.ERROR, "Decision engine produced an incomplete result.")
            self.decision_process = None
            self._full_analysis_after_decision(succeeded=False)
            return
        self.latest_decision_report = report_path
        self._render_decision_result(report)
        try:
            state=self._state_from_ui(); bundle=self._selected_bundle_for_state(state)
            production_players=load_players(bundle.parent/"current_players.json")
            fixtures = FixtureDisplayRepository(bundle.parent/"current_players.json")
            self._install_strategy_previews(
                report, state=state, players=production_players, fixtures=fixtures,
            )
        except DesktopEngineError as exc:
            self._append_engine_log(f"RECOMMENDED XI: {exc}"); self._set_decision_run_state(DecisionRunState.ERROR,"Decision result cannot be shown as a lineup preview."); self.decision_process=None; self._full_analysis_after_decision(succeeded=False); return
        self._append_engine_log(f"DECISION ENGINE: PASS\nReport: {report_path}")
        self._set_decision_run_state(DecisionRunState.SUCCESS, "Decision recommendation ready.")
        self.decision_process = None
        self._full_analysis_after_decision(succeeded=True)

    def start_chip_run(self) -> None:
        if self.chip_process is not None and self.chip_process.state() != QProcess.ProcessState.NotRunning:
            self.statusBar().showMessage("Chip screen is already running.", 5000)
            return
        if any(process is not None and process.state() != QProcess.ProcessState.NotRunning for process in (self.engine_process, self.account_process, self.decision_process)):
            QMessageBox.information(self, "Engine busy", "Wait for the current process to finish.")
            return
        if self.latest_decision_report is None:
            self._set_chip_run_state(ChipRunState.ERROR, "Run the Decision Engine before the chip screen.")
            return
        state = self._state_from_ui()
        try:
            validate_state(state, self.players)
            python = resolve_engine_python(self.root)
            if self.selected_projection_bundle is None:
                raise DesktopEngineError("Select a compatible production projection run before continuing.")
            bundle = chip_bundle_for_state(self.root, state, self.selected_projection_bundle)
            request = write_decision_request(self.root / "data" / "interim" / "desktop_chip" / "request.json", state)
            arguments = chip_arguments(
                request_path=request, prediction_bundle=bundle, decision_report=self.latest_decision_report,
                output_dir=self.root / "data" / "processed" / "desktop_chips" / state.season.replace("/", "-"),
            )
        except (DesktopStateError, DesktopEngineError) as exc:
            self._append_engine_log(f"CHIP SCREEN: {exc}")
            self._set_chip_run_state(ChipRunState.ERROR, "Chip screen needs matching saved production data.")
            return
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment(); environment.insert("PYTHONUTF8", "1"); environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment); process.setWorkingDirectory(str(self.root))
        process.readyReadStandardOutput.connect(self._read_chip_stdout); process.readyReadStandardError.connect(self._read_chip_stderr)
        process.finished.connect(self._chip_finished); process.errorOccurred.connect(self._chip_process_error)
        self.chip_process = process; self._chip_stdout = ""; self._chip_cancel_requested = False; self.engine_progress.setRange(0, 0)
        if self.full_analysis_state is not FullAnalysisState.CHIP_SCREEN:
            self.engine_log.clear()
        self._set_chip_run_state(ChipRunState.RUNNING, "Chip screen running...")
        self._append_engine_log(f"=== CHIP SCREEN ===\nUsing saved projection bundle: {bundle}\nUsing decision report: {self.latest_decision_report}\nCommand: {python} {' '.join(arguments)}")
        process.start(str(python), arguments)

    def _chip_process_error(self, error) -> None:
        self._append_engine_log(f"Chip screen QProcess error: {error}")

    def _chip_finished(self, exit_code, exit_status) -> None:
        self._read_chip_stdout(); self._read_chip_stderr(); self.engine_progress.setRange(0, 1); self.engine_progress.setValue(1)
        if self._chip_cancel_requested:
            self._chip_cancel_requested = False
            self.chip_process = None
            self._set_chip_run_state(ChipRunState.CANCELLED, "Chip analysis cancelled.")
            self._full_analysis_after_chip(outcome="was cancelled")
            return
        if int(exit_code) != 0:
            self._append_engine_log(f"CHIP SCREEN: FAILED (exit {exit_code})")
            self._set_chip_run_state(ChipRunState.ERROR, "Chip screen could not produce a recommendation.")
            self.chip_process = None
            self._full_analysis_after_chip(outcome="failed")
            return
        try:
            report_path = chip_report_path(self._chip_stdout)
            if report_path is None:
                raise DesktopEngineError("No chip report path was returned by the existing chip screen.")
            report = load_chip_report(report_path)
            if report.external_mutations:
                raise DesktopEngineError("Chip output failed the read-only safety check.")
        except DesktopEngineError as exc:
            self._append_engine_log(f"CHIP SCREEN: {exc}")
            self._set_chip_run_state(ChipRunState.ERROR, "Chip screen produced an incomplete result.")
            self.chip_process = None
            self._full_analysis_after_chip(outcome="failed")
            return
        self.latest_chip_report = report_path
        self.analysis_chip_summary.setText(format_chip_summary(report))
        self._append_engine_log(f"CHIP SCREEN: PASS\nReport: {report_path}")
        self._set_chip_run_state(ChipRunState.SUCCESS, "Chip recommendation ready.")
        self.chip_process = None
        self._full_analysis_after_chip(outcome="success")

    def start_projection_run(self) -> None:
        if any(process is not None and process.state()!=QProcess.ProcessState.NotRunning for process in (self.engine_process, self.decision_process, self.chip_process, self.account_process)):
            QMessageBox.information(self,"Engine busy","A projection run is already in progress."); return
        state=self._state_from_ui()
        try:
            validate_state(state,self.players); python=resolve_engine_python(self.root)
            arguments=projection_arguments(season=state.season,gameweek=state.gameweek,simulation_count=self.simulation_spin.value(),seed=self.seed_spin.value())
        except (DesktopStateError,DesktopEngineError) as exc:
            QMessageBox.warning(self,"Cannot run projections",str(exc)); return
        save_state(self.state_path,state)
        process=QProcess(self); environment=QProcessEnvironment.systemEnvironment(); environment.insert("PYTHONUTF8","1"); environment.insert("PYTHONIOENCODING","utf-8"); environment.remove("FPL_SIMULATOR_CHALLENGER")
        process.setProcessEnvironment(environment); process.setWorkingDirectory(str(self.root)); process.readyReadStandardOutput.connect(self._read_engine_stdout); process.readyReadStandardError.connect(self._read_engine_stderr); process.finished.connect(self._projection_finished); process.errorOccurred.connect(self._projection_process_error)
        self.engine_process=process; self.run_projections.setEnabled(False); self.engine_progress.setRange(0,0); self.engine_log.clear()
        self._append_engine_log(f"=== PRODUCTION V22 PROJECTION RUN ===\nSeason: {state.season}\nGW: {state.gameweek}\nCommand: {python} {' '.join(arguments)}")
        self.statusBar().showMessage("Running production projections..."); process.start(str(python),arguments)

    def _projection_process_error(self,error) -> None:
        self._append_engine_log(f"QProcess error: {error}")

    def _projection_finished(self,exit_code,exit_status) -> None:
        self._read_engine_stdout(); self._read_engine_stderr(); self.engine_progress.setRange(0,1); self.engine_progress.setValue(1); self.run_projections.setEnabled(True)
        if int(exit_code)!=0:
            self._append_engine_log("PROJECTION RUN: FAILED"); self.statusBar().showMessage(f"Projection run failed (exit {exit_code}).",10000); return
        state=self._state_from_ui(); run_dir=latest_prediction_run(self.root,state.season,gameweek=state.gameweek)
        if run_dir is None:
            self._append_engine_log("No matching complete projection run was found."); return
        try: summary=projection_run_summary(run_dir)
        except DesktopEngineError as exc: self._append_engine_log(str(exc)); return
        self.latest_projection_run=run_dir; self.selected_projection_bundle=run_dir / "shadow_projection_bundle.json"; self._refresh_run_center(selected_projection_run_id=run_dir.name); self._append_engine_log(f"PROJECTION RUN: PASS\nManifest: {summary['manifest']}"); self.statusBar().showMessage(f"Production projections ready: {run_dir.name}",12000)

    def _edge_executable(self):
        candidates=[]; discovered=shutil.which("msedge")
        if discovered: candidates.append(Path(discovered))
        for variable in ("ProgramFiles(x86)","ProgramFiles","LOCALAPPDATA"):
            base=os.environ.get(variable)
            if base: candidates.append(Path(base)/"Microsoft"/"Edge"/"Application"/"msedge.exe")
        return next((candidate for candidate in candidates if candidate.exists()),None)

    def _account_primary_action(self) -> None:
        if not self._cdp_probe():
            self.open_fpl_login()
            return
        self.start_account_sync()

    def open_fpl_login(self) -> None:
        self._login_window_launched = False
        self._set_account_sync_state(AccountSyncState.CONNECTING)
        edge=self._edge_executable(); local_app_data=os.environ.get("LOCALAPPDATA")
        if edge is None or not local_app_data:
            self._append_engine_log("FPL login launch failed: Microsoft Edge or LOCALAPPDATA is unavailable.")
            self._set_account_sync_state(AccountSyncState.ERROR)
            self.statusBar().showMessage("FPL login could not be opened.",10000); return
        profile=Path(local_app_data)/"FPLControlCenter"/"manual_edge_profile"; profile.mkdir(parents=True,exist_ok=True)
        try:
            subprocess.Popen([str(edge),"--remote-debugging-address=127.0.0.1","--remote-debugging-port=9222",f"--user-data-dir={profile}","--no-first-run","--no-default-browser-check","https://fantasy.premierleague.com/my-team"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError as exc:
            self._append_engine_log(f"FPL login launch failed: {type(exc).__name__}: {exc}")
            self._set_account_sync_state(AccountSyncState.ERROR)
            self.statusBar().showMessage("FPL login could not be opened.",10000); return
        self._login_window_launched = True
        self._set_account_sync_state(AccountSyncState.LOGIN_REQUIRED)
        self.statusBar().showMessage("Log in to FPL in the opened Edge window, then click Retry sync.",12000)

    def start_account_sync(self) -> None:
        if any(process is not None and process.state()!=QProcess.ProcessState.NotRunning for process in (self.engine_process,self.account_process,self.decision_process,self.chip_process)):
            QMessageBox.information(self,"Engine busy","Wait for the current process to finish."); return
        if not self._cdp_probe():
            self._login_window_launched = False
            self._append_engine_log("FPL sync preflight: CDP endpoint unavailable at 127.0.0.1:9222.")
            self._set_account_sync_state(AccountSyncState.LOGIN_REQUIRED)
            self.statusBar().showMessage("Open FPL login, sign in, then retry sync.",12000)
            return
        script=self.root/"scripts"/"desktop003b3_cdp_sync.py"
        if not script.exists():
            self._append_engine_log(f"FPL sync helper is missing: {script}")
            self._set_account_sync_state(AccountSyncState.ERROR); self.statusBar().showMessage("FPL sync is unavailable.",10000); return
        try: python=resolve_engine_python(self.root)
        except DesktopEngineError as exc:
            self._append_engine_log(f"FPL sync Python resolution failed: {exc}")
            self._set_account_sync_state(AccountSyncState.ERROR); self.statusBar().showMessage("FPL sync is unavailable.",10000); return
        process=QProcess(self); environment=QProcessEnvironment.systemEnvironment(); environment.insert("PYTHONUTF8","1"); environment.insert("PYTHONIOENCODING","utf-8")
        process.setProcessEnvironment(environment); process.setWorkingDirectory(str(self.root)); process.readyReadStandardOutput.connect(self._read_account_stdout); process.readyReadStandardError.connect(self._read_account_stderr); process.finished.connect(self._account_sync_finished); process.errorOccurred.connect(self._account_process_error)
        self.account_process=process; self._set_account_sync_state(AccountSyncState.SYNCING); self.engine_progress.setRange(0,0); self.engine_log.clear()
        self._append_engine_log("=== FPL ACCOUNT SYNC ===\nRead-only account synchronization. No transfers or chip actions will be executed.")
        self.statusBar().showMessage("Synchronizing FPL account..."); process.start(str(python),["-u",str(script)])

    def _read_account_stdout(self) -> None:
        if self.account_process is not None: self._append_engine_log(bytes(self.account_process.readAllStandardOutput()).decode("utf-8",errors="replace"))

    def _read_account_stderr(self) -> None:
        if self.account_process is not None: self._append_engine_log(bytes(self.account_process.readAllStandardError()).decode("utf-8",errors="replace"))

    def _account_process_error(self,error) -> None:
        self._append_engine_log(f"FPL sync QProcess error: {error}")
        self._set_account_sync_state(AccountSyncState.ERROR)

    def _account_sync_finished(self,exit_code,exit_status) -> None:
        self._read_account_stdout(); self._read_account_stderr(); self.engine_progress.setRange(0,1); self.engine_progress.setValue(1)
        if int(exit_code)!=0:
            self._append_engine_log(f"FPL ACCOUNT SYNC: FAILED (exit {exit_code})")
            self._set_account_sync_state(AccountSyncState.LOGIN_REQUIRED if int(exit_code) in {21,23} else AccountSyncState.ERROR)
            self.statusBar().showMessage("FPL login is required." if int(exit_code) in {21,23} else "FPL account sync failed.",10000); self.account_process=None; return
        try:
            state=load_state(self.state_path); validate_state(state,self.players)
        except DesktopStateError as exc:
            self._append_engine_log(f"FPL ACCOUNT SYNC INVALID: {exc}"); self._set_account_sync_state(AccountSyncState.ERROR); self.account_process=None; return
        issues = account_state_issues(state, self.players)
        if issues:
            self._append_engine_log("FPL ACCOUNT SYNC INCOMPLETE:\n" + "\n".join(f"- {issue}" for issue in issues))
            self._set_account_sync_state(AccountSyncState.ERROR, "account data incomplete"); self.account_process=None; return
        planning_changed = planning_state_changed(self._current_state, state)
        self._clear_strategy_previews()
        if planning_changed:
            self.latest_decision_report = None
            self.latest_chip_report = None
            self._active_analysis_run_id = None
            self._active_analysis_state = None
            self._full_analysis_bundle = None
            self._clear_captaincy_result()
            self._clear_transfer_targets()
            self.analysis_chip_summary.setText("Planning context changed after FPL sync — run a new analysis.")
            self._append_engine_log("PLANNING CONTEXT: active decision and chip results cleared after account state changed.")
        self._apply_state(state)
        self._set_account_sync_state(AccountSyncState.CONNECTED, f"prices 15/15 · FT {state.free_transfers}")
        self._append_engine_log("FPL ACCOUNT SYNC: PASS")
        self.statusBar().showMessage(f"FPL account synchronized: 15 players, FT {state.free_transfers}, bank £{state.bank_tenths/10:.1f}m.",12000); self.account_process=None

    def validate_current_state(self) -> bool:
        try: validate_state(self._state_from_ui(),self.players)
        except DesktopStateError as exc: QMessageBox.warning(self,"Invalid squad",str(exc)); return False
        QMessageBox.information(self,"Squad valid","The current squad is valid under FPL squad constraints."); return True

    def save_current_state(self) -> None:
        state=self._state_from_ui()
        try: validate_state(state,self.players)
        except DesktopStateError as exc: QMessageBox.warning(self,"Cannot save squad",str(exc)); return
        save_state(self.state_path,state); self._current_state=state; self._refresh_account_status(state); self._refresh_pitch_view(); self.statusBar().showMessage("Squad state saved to data/user/squad_state.json",5000)

    def reset_saved_wc(self) -> None:
        state=bootstrap_saved_wc(self.root)
        if len(state.player_ids)!=15:
            QMessageBox.warning(self,"Saved Wildcard unavailable","The preserved GW4 WC reference could not be loaded."); return
        self._apply_state(state); self._refresh_account_status(state); self.statusBar().showMessage("Restored preserved GW4 WC squad.",5000)
