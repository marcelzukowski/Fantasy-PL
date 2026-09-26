# AGENTS.md â€” FPL Prediction Engine / FPL Control Center

> **Canonical handoff file for every new coding agent.**
>
> Read this file before changing the project. After every successfully verified feature, bug fix, migration, or milestone, update the relevant sections of this file before considering the task complete.
>
> This file is intentionally kept in the repository root so that Codex/agents can discover it immediately.

---

## 1. Project purpose

This repository is an **FPL prediction and decision engine** plus a Windows desktop GUI named **FPL Control Center**.

Primary goals:

1. Predict Fantasy Premier League points for roughly **1â€“8 upcoming gameweeks**.
2. Use production simulation rather than simple one-game heuristics.
3. Support real FPL squad constraints, personal selling prices, bank, free transfers, and chip state.
4. Generate actionable decisions:
   - transfers OUT / IN,
   - recommended starting XI,
   - captain / vice-captain,
   - chip recommendations,
   - rolling multi-GW transfer planning.
5. Present the result in a desktop GUI that is useful to a normal FPL manager, not only to the engine developer.

Current season in active development: **2026/27**.

---

## 2. Mandatory agent operating rules

### 2.1 Read before changing anything

Before modifying code:

1. Read this `AGENTS.md`.
2. Inspect the exact current implementation before patching.
3. Do not assume that code shown in an older chat or old context ZIP is still current.
4. Prefer small, testable stages with explicit gates.
5. Do not overwrite working architecture merely to satisfy a visual preference.

### 2.2 User workflow

The preferred collaboration workflow is:

1. Agent provides **one terminal-ready PowerShell block**.
2. User pastes it into the project terminal.
3. User returns the complete output or a generated log file.
4. Agent analyzes the result.
5. Agent provides only the next concrete step.

Avoid giving many alternative commands unless explicitly requested.

### 2.3 External agent / Codex prompts

Every future prompt prepared for an external coding agent / Codex should begin with:

- **recommended model**, and
- **recommended reasoning effort**,

with the goal of good engineering quality while avoiding unnecessary token use.

### 2.4 Completion criteria

A feature is **not complete** just because the code compiles.

A stage may be marked complete only when its required checks are green, normally including the relevant subset of:

- Python compile check,
- focused tests,
- GUI smoke test,
- full pytest suite for substantial changes,
- frozen-engine hash guard,
- PyInstaller build,
- copied root `FPLControlCenter.exe`,
- live/manual visual check when UI is changed.

If a gate is non-zero, document the failure and do not describe the milestone as complete.

---

## 3. Safety / account rules

### 3.1 FPL account access is read-only

The desktop application currently uses FPL account access only to **read**:

- current squad,
- purchase prices,
- selling prices,
- bank,
- free-transfer state,
- chip usage,
- account/entry context.

The application must **not** automatically execute:

- transfers,
- chip activations,
- captain changes,
- vice-captain changes,
- squad confirmations,
- any other account mutation.

### 3.2 Credentials and tokens

Never ask the user to paste an FPL/Google/Premier League password into:

- chat,
- PowerShell,
- a config file,
- source code.

Current login flow:

1. Dedicated normal Microsoft Edge instance is launched with remote debugging.
2. User logs into the official Premier League/FPL site in that browser.
3. The local sync helper attaches to the already logged-in browser session.
4. The FPL bearer token is captured only in process memory from authenticated browser traffic.
5. The token must not be printed.
6. The token must not be committed.
7. The token must not be written into the project.

Current helper:
`script/desktop003b3_cdp_sync.py` or `scripts/desktop003b3_cdp_sync.py` depending on the live repository path. Verify the exact path before editing.

### 3.3 Google login

Google may reject login in a browser directly launched under browser automation. The working approach is:

- launch a normal Edge instance with remote debugging,
- let the user log in normally,
- attach to that existing browser session.

Do not attempt to bypass Google anti-automation protections.

---

## 4. Core project architecture

Project root on the development machine is normally:

`C:\Users\Marcel\Desktop\fpl-prediction-engine`

Important top-level areas:

- `src/` â€” prediction/decision engine code.
- `desktop_app/` â€” PySide6 desktop application.
- `scripts/` â€” project and desktop helper scripts.
- `tests/` â€” test suite.
- `data/` â€” processed/user/runtime data.
- `scratch/` â€” staged experiments, audits, temporary decision runs, desktop milestone logs.
- `docs/` â€” documentation.
- `config/` â€” configuration.
- `FPLControlCenter.exe` â€” latest copied desktop executable.
- `build/`, `dist/` â€” PyInstaller outputs.

Do not treat `scratch/` runs as production merely because they are newer.

---

## 5. Desktop state contract

Main state module:

`desktop_app/state.py`

Core model:

`DesktopSquadState`

Important state concepts:

- `season`
- `gameweek`
- `bank_tenths`
- `free_transfers`
- `player_ids`
- `chips_used`
- `source`
- `updated_at`
- `fpl_entry_id`
- `selling_prices_tenths`
- `purchase_prices_tenths`

Expected squad constraints:

- exactly 15 unique players,
- 2 GK,
- 5 DEF,
- 5 MID,
- 3 FWD,
- max 3 players per real club,
- bank >= 0,
- free transfers within supported FPL range.

Position counts:

```python
POSITION_COUNTS = {
    "GK": 2,
    "DEF": 5,
    "MID": 5,
    "FWD": 3,
}
```

State persistence:

`data/user/squad_state.json`

Do not hardcode live user squad values into source code or documentation. Runtime account values belong in state/data files.

### 5.1 Personal price preservation

A critical contract is that GUI operations must not silently erase:

- `fpl_entry_id`,
- `selling_prices_tenths`,
- `purchase_prices_tenths`.

`preserve_account_state(...)` was added for this reason.

If the manually selected squad changes, price maps should be retained only for players for whom they remain valid. Never invent selling prices for newly selected players.

---

## 6. Player data contract

Main module:

`desktop_app/data_access.py`

`PlayerRecord` includes at least:

- canonical `player_id`,
- `display_name`,
- `position`,
- `team_id`,
- `current_price`,
- optional FPL `provider_id`.

The production desktop player source currently resolves through existing processed/scratch artifacts and must be inspected before changing source-selection logic.

Important distinction:

- `player_id` = internal/canonical engine identifier.
- `provider_id` = external FPL element identifier used to map `/api/my-team/...` picks to canonical engine players.

At the last verified account-sync milestone, provider-ID coverage was complete for the live player pool.

---

## 7. FPL account sync contract

Main module:

`desktop_app/fpl_account.py`

Important concepts:

### `FPLAccountSnapshot`

Represents authenticated read-only account state, including:

- entry/account identifier,
- 15 canonical player IDs,
- personal selling prices,
- personal purchase prices,
- bank,
- free transfers,
- chip state,
- captain / vice-captain when available,
- transfer-limit metadata.

### `/api/my-team/{entry_id}/`

The current integration maps FPL `element` IDs through `provider_id`.

Required account-sync gate:

- squad: 15/15,
- selling prices: 15/15,
- purchase prices: 15/15,
- bank parsed,
- free-transfer state parsed,
- state validates,
- local write verifies.

### Free-transfer semantics

Do **not** interpret `transfers.status == "cost"` as zero free transfers.

Verified current parser rule:

```text
if limit is None:
    remaining FT = None
else:
    remaining FT = max(limit - made, 0)
```

The account API returned a real case with:

```text
status = cost
limit  = 3
made   = 0
cost   = 4
```

which correctly means **3 remaining free transfers**, not 0.

Keep the regression test for this behavior.

---

## 8. Prediction engine / production simulator

The current production simulator is:

`fixture_simulator_v22_lineup_coherent_logit`

Short name: **V22**.

Do not silently substitute an older simulator because a scratch run is newer.

A prior desktop preflight found:

- historical complete V22 run for GW4 in scratch,
- no fresh production V22 GW5 run at that time,
- a newer scratch V1 run that must **not** be treated as the production default.

Current production flow should be:

1. user state is valid,
2. run fresh projections for selected GW,
3. verify resulting bundle/run uses V22,
4. only then allow the decision engine to consume the run.

The desktop projection action is driven through:

`desktop_app/orchestration.py`

Important helpers include:

- `resolve_engine_python`
- `projection_arguments`
- `latest_prediction_run`
- `projection_run_summary`

Projection CLI pattern:

```text
python -m fpl_engine predict-current
    --season <season>
    --gameweek <gw>
    --simulation-count <n>
    --seed <seed>
```

Verify the actual current argument contract before modifying it.

---

## 9. Decision-engine architecture

Known decision APIs include:

### Availability

```python
build_gameweek_availability(
    projection_rows,
    minute_rows,
    *,
    strict=True,
)
```

Returns availability keyed approximately by `(player_id, gameweek)`.

### Rolling free-transfer optimization

```python
optimize_rolling_free_transfers(
    *,
    players,
    projections_by_id,
    state,
    horizon,
    transfers_now,
    current_free_transfers,
    max_free_transfers=5,
    captaincy_weight=1.0,
    fixed_squad_now_player_ids=None,
    appearance_by_player_gameweek=None,
)
```

### Chip screening

```python
screen_chips_exact(
    *,
    player_rows,
    positions,
    projections_by_id,
    p_appearance_by_gameweek,
    current_player_ids,
    selling_prices_tenths,
    bank_tenths,
    first_gameweek,
    wildcard_horizon,
    wildcard_weights,
    max_players_per_team=3,
)
```

Before changing signatures, inspect the live implementation and tests.

Decision-engine output should eventually drive the desktop UI:

- transfers OUT,
- transfers IN,
- recommended XI,
- captain,
- vice-captain,
- chip recommendation,
- multi-GW value / EV context.

---

## 10. Desktop GUI architecture

Main modules:

- `desktop_app/main_window.py`
- `desktop_app/squad_pitch.py`

GUI technology: **PySide6**.

### Current successful visual architecture before the tabbed-layout milestone

The desktop UI currently has:

- compact account/gameweek context,
- owned squad list of 15 players,
- pitch showing 11 players,
- `Current XI`,
- disabled `Recommended XI` placeholder until decision output exists,
- transfer bar prepared for `OUT -> IN`,
- chips panel,
- squad-state/account actions,
- projection controls,
- engine log.

The one-screen geometry was successfully validated with:

- 15 owned players,
- 11 current XI players,
- pitch rows fitting,
- `vertical scroll max = 0`.

However, even with zero scroll, the single-screen layout remained visually crowded.

### Planned / next visual milestone

**DESKTOP-003C6 â€” tabbed application layout**

Target navigation:

```text
Squad | Analysis | Engine
```

Intended responsibilities:

#### Squad tab

User-facing FPL screen:

- owned 15-player squad,
- current XI,
- recommended XI,
- OUT / IN transfer visualization,
- edit squad action.

No engine log, chip settings, or technical controls here.

#### Analysis tab

Model result screen:

- Run projections,
- Run decision engine,
- Run chip screen,
- Run full analysis,
- transfer recommendations,
- captaincy recommendations,
- chip recommendation,
- future projection/EV tables,
- recommended XI state.

#### Engine tab

Technical / configuration screen:

- simulation count,
- seed,
- chips-used state,
- FPL login/sync,
- validate/save/reset state,
- progress,
- engine log.

This separation is preferred over further shrinking font sizes and control heights.

---

## 11. Squad dashboard semantics

The UI must distinguish clearly between:

### Owned squad

Exactly 15 players currently owned.

This list should remain stable and explicit.

### Current XI

The current or baseline starting XI.

Pitch should show **11**, not all 15.

### Recommended XI

Decision-engine output.

Must stay disabled/unavailable until a valid decision result exists.

Never fabricate a recommended XI just to make the button active.

### Transfer plan

Once the decision engine is connected:

- outgoing player: red `OUT` or red downward/exit indicator,
- incoming player: green `IN` or green incoming indicator,
- transfer bar example:
  `OUT: Tavernier -> IN: Saka`,
- incoming players should receive an `IN` badge on Recommended XI,
- outgoing owned players should be clearly marked in the owned-squad list.

Later add:

- `C` captain badge,
- `VC` vice-captain badge.

---

## 12. GUI behavior that must not regress

When changing layout or styling:

1. `player_boxes` must continue to exist because state/edit logic depends on them.
2. `chip_boxes` must continue to contain the 8 chip controls.
3. `run_projections` must remain connected to the production projection runner.
4. `run_decision`, `run_chips`, `run_full` should not be enabled before their production contracts are ready.
5. account sync must preserve personal prices and FT.
6. `pitch_widget.refresh(...)` must remain driven from live player selections/state.
7. manual squad editor may be hidden/collapsed, but it must remain functional.
8. engine log must remain available somewhere, even if moved to a technical tab.
9. do not remove account safety messaging/behavior simply for visual cleanup.
10. PyInstaller must include any newly created desktop modules.

---

## 13. Frozen-engine rule

A frozen baseline manifest exists under processed advanced data, currently named similarly to:

`data/processed/advanced/baseline_manifest_20260910T113453Z.json`

Desktop/UI work must not unexpectedly modify frozen engine files.

Typical guard:

1. load manifest,
2. calculate SHA-256 for each listed file,
3. compare with saved hash,
4. fail the stage if any frozen file changed unintentionally.

If a future milestone intentionally changes frozen engine code, that must be a deliberate engine milestone, not an accidental side effect of GUI work.

---

## 14. Testing expectations

Recent known verified states:

- substantial GUI/account milestones previously passed the full suite with roughly:
  `1225 passed, 2 skipped`
- focused desktop regression suite:
  `17 passed`

Do **not** use those numbers as permanent assertions. Test counts will grow.

Important desktop test areas:

- `tests/test_desktop_state.py`
- `tests/test_desktop_account_state_bridge.py`
- `tests/test_desktop_fpl_account.py`
- `tests/test_desktop_orchestration.py`

When adding a behavior, add a regression test when practical.

For GUI smoke tests, use:

```text
QT_QPA_PLATFORM=offscreen
```

Qt can print a font-directory warning in this environment. Distinguish benign Qt font warnings from actual assertion/traceback failures.

---

## 15. PyInstaller / EXE rule

Desktop release artifact:

`FPLControlCenter.exe`

Typical build:

```text
python -m PyInstaller
    --noconfirm
    --clean
    --onefile
    --windowed
    --name FPLControlCenter
    --paths .
    desktop_app/main.py
```

PyInstaller commonly writes informational output to stderr. In PowerShell this can be confusing, so subprocess wrappers that merge stdout/stderr into a UTF-8 log are preferred.

After successful build:

1. confirm `dist/FPLControlCenter.exe` exists,
2. copy it to repository root,
3. verify copied executable,
4. report timestamp/size if useful.

Never claim a new EXE was built if build/copy was skipped because a prior gate failed.

---

## 16. Data-source philosophy

Preferred data sources should be:

- free where practical,
- reproducible,
- cached,
- modular,
- replaceable.

Known data-source work includes:

- official FPL API,
- Understat,
- FBref,
- Vaastav,
- fplcache,
- API-Football,
- StatsBomb Open,
- football-data,
- local FPL snapshots.

FBref has historically been unreliable because of robots/403 access restrictions. Do not make critical production logic depend on live FBref availability without fallback.

---

## 17. Project principles

### Prediction quality

Prefer calibrated/reproducible model improvements over visually impressive but unjustified scores.

### Decision quality

A recommendation is useful only if it respects:

- actual owned squad,
- personal selling prices,
- bank,
- free transfers,
- FPL squad constraints,
- availability,
- time horizon,
- transfer costs,
- chip state.

### UI philosophy

The desktop app should behave like a football/FPL decision tool, not an admin form.

Prefer:

- clear information hierarchy,
- squad-first UI,
- visual XI,
- dedicated analysis screen,
- technical settings separated from user-facing decisions,
- readable defaults.

Do not solve layout pressure by indefinitely shrinking every widget.

### Reproducibility

Important runs should record:

- season,
- GW,
- seed,
- simulation count,
- simulator/version,
- input artifact lineage,
- output artifact path.

---

## 18. Current project status

Last known successful major capabilities:

### Engine/data

- modular engine structure exists,
- current-player data pipeline exists,
- production V22 simulator exists,
- historical V22 run artifacts exist,
- decision/availability/chip APIs exist.

### Account sync

Working read-only FPL account sync:

- normal Edge login,
- browser CDP attach,
- bearer captured in memory only,
- FPL entry/account resolved,
- 15-player squad mapped,
- 15/15 selling prices,
- 15/15 purchase prices,
- bank parsed,
- free transfers parsed correctly,
- chip state parsed,
- local state saved,
- no FPL mutation.

### Desktop

Working:

- account sync controls,
- state preservation,
- projection run bridge,
- owned-15 squad dashboard,
- 11-player current XI pitch,
- transfer visualization placeholders,
- `Recommended XI` placeholder,
- PyInstaller build.

### Latest known UI conclusion

The one-screen dashboard passed technical geometry checks, but remained visually too crowded.

Therefore the next preferred UI architecture is:

**`Squad | Analysis | Engine` tabs.**

### Next functional milestone after UI settles

1. Generate a **fresh production V22 prediction run for GW5**.
2. Verify simulator identity and artifact completeness.
3. Connect `Run decision engine`.
4. Feed decision output into:
   - Recommended XI,
   - OUT / IN,
   - captain / vice,
   - analysis summaries.
5. Connect chip screen.
6. Connect Full GW Analysis.

---

## 19. Known pitfalls / lessons learned

1. **Do not infer personal selling prices from generic historical candidate pools.**
   They are not authoritative account values.

2. **Do not select the newest scratch prediction run blindly.**
   It may be an older/challenger simulator such as V1 rather than production V22.

3. **Do not infer FT=0 from `status="cost"`.**
   Use `limit - made`.

4. **Do not let GUI save operations erase account-derived fields.**

5. **Do not launch Google login directly inside a Playwright-controlled browser.**
   Google may block it as insecure/automated.

6. **PowerShell encoding can break output containing `ÂŁ`.**
   Use UTF-8 (`PYTHONUTF8`, `PYTHONIOENCODING`, or stdout reconfigure) when necessary.

7. **PowerShell can treat native stderr as an error.**
   Prefer Python subprocess wrappers for PyInstaller or long native commands.

8. **Do not trust a GUI smoke test that only checks widget existence.**
   For visual work also verify actual geometry and perform a real screenshot/manual check.

9. **Zero scroll does not automatically mean good UX.**
   The UI can mathematically fit and still be visually overcrowded.

10. **Inspect the live source before patching.**
    Multiple failed UI stages came from assuming obsolete anchors.

---

## 20. Maintenance rule for this file

After every successful milestone, update this file.

Do **not** append raw terminal logs.

Update the smallest relevant sections and add one short changelog entry below.

Each changelog entry should contain:

- date,
- milestone ID,
- short description,
- important contracts changed,
- tests/gates,
- next step.

If a milestone fails, do not add it as completed. Add it only if the failure itself revealed a durable rule that belongs in `Known pitfalls / lessons learned`.

---

## 21. Changelog

### 2026-09-18 — DESKTOP-PACKAGING-DIAG — ONEFILE startup verification

Verified:
- temporary console ONEDIR diagnostic reached the `FPL Control Center` main window and event loop with no stdout, stderr or traceback,
- the same temporary console ONEFILE diagnostic reached its child-process main window after onefile extraction,
- `desktop_app.analysis_views`, `desktop_app.transfer_targets`, Run Center, captaincy, `qt_material6`, PL styles/assets and the explicitly packaged Market Shadow sources are present,
- no startup action invokes projections, account sync, bookmaker calls, Decision Engine, Chip Screen or history recomputation,
- the final windowed ONEFILE and root copy both launched and closed cleanly.

Packaging note:
- a cold ONEFILE launch can exceed a short 20–35 second process-handle probe while its parent extracts and starts the child process. This was an acceptance-probe timeout, not a missing module or application startup exception.

### 2026-09-17 — DESKTOP-ANALYSIS-USABILITY — Analysis readability

Completed:
- replaced clipped Analysis card labels with wrapped, selectable, scrollable summaries,
- removed the redundant Recommended XI helper line from Analysis,
- replaced the dense Top player targets text block with a readable, position-filtered table sourced from the canonical production bundle,
- added display-only Top 3 transfer options: the existing engine recommendation plus two same-position candidates from the existing weighted 6-GW ranking.

Verified:
- desktop Analysis/decision/transfer-target focused suite passed (30 tests),
- offscreen 1600x820 geometry check passed,
- no FPL account mutation, projection rerun, decision change, chip change, or external call was introduced.

### 2026-09-14 â€” DESKTOP-003B2 â€” Account sync core

Added:

- personal FPL price fields to desktop state,
- provider-ID mapping,
- authenticated my-team parser,
- account snapshot application,
- regression tests.

Result: account data model ready for live sync.

### 2026-09-14 â€” DESKTOP-003B3 / B3B / B3E â€” Live account synchronization

Added/verified:

- normal Edge login workflow,
- CDP attach,
- bearer capture without printing/storing token,
- authenticated my-team read,
- personal BUY/SELL prices,
- bank,
- chip state,
- state write verification.

Fixed:

- direct-script import path,
- Windows UTF-8 console issue.

### 2026-09-14 â€” DESKTOP-003B3D â€” Free-transfer semantics fix

Fixed FT parser.

Regression behavior:

`status=cost, limit=3, made=0 -> 3 FT`.

### 2026-09-14 â€” DESKTOP-003B4A â€” Account sync in GUI

Added:

- Open FPL login,
- Sync FPL account,
- account status,
- preservation of personal account fields when GUI state is saved,
- rebuilt executable.

### 2026-09-14 â€” DESKTOP-003C2..C5 â€” Squad dashboard iteration

Introduced:

- FPL-like visual pitch,
- owned 15-player list,
- current XI with 11 players,
- Recommended XI placeholder,
- transfer OUT/IN display contract,
- zero-scroll geometry,
- visual cleanup.

Conclusion:

Single-screen layout is functionally valid but visually overcrowded. Tabs are preferred.

### NEXT â€” DESKTOP-003C6

Implement:

`Squad | Analysis | Engine`

without regressing account sync, state preservation, prediction runner, squad editing, or engine logs.

---

## 22. Agent end-of-task checklist

Before reporting success, answer all of these:

- [ ] Did I inspect the live code before patching?
- [ ] Did I preserve FPL read-only safety?
- [ ] Did I preserve personal selling/purchase prices?
- [ ] Did I preserve the frozen-engine contract?
- [ ] Did compile pass?
- [ ] Did relevant tests pass?
- [ ] Did GUI smoke pass if GUI changed?
- [ ] Did full suite pass if the change was substantial?
- [ ] Did PyInstaller build/copy pass if an EXE was requested?
- [ ] Did I verify the actual production simulator where relevant?
- [ ] Did I avoid relying on scratch artifacts as production?
- [ ] Did I update this `AGENTS.md` with the successful change?
- [ ] Is the stated next step still accurate?

If any required answer is â€śnoâ€ť, do not describe the stage as complete.

## 2026-09-14 â€” DESKTOP-003C6D5 â€” Squad card lifecycle fix

Completed:
- fixed temporary accumulation of stale XI widgets during repeated state refreshes,
- `_clear_pitch()` now hides and detaches obsolete cards before `deleteLater()`,
- initial GUI state now contains exactly 11 XI cards without requiring deferred-delete flushing,
- retained final Squad visual dimensions,
- retained hidden numeric spin arrows,
- retained brand green #167A3F,
- retained GBP runtime prefix,
- rebuilt root FPLControlCenter.exe.

Verified:
- owned squad = 15,
- Current XI = 11,
- XI card widgets = 11,
- shirt widgets = 11,
- stale cards = 0,
- focused suite passed,
- full suite passed,
- frozen-engine guard passed,
- EXE build/copy passed.

Desktop visual layout is now frozen.

Next:
- run fresh production V22 projections for GW5,
- verify fixture_simulator_v22_lineup_coherent_logit,
- connect Decision Engine,
- populate Recommended XI,
- populate OUT / IN,
- populate captain / vice-captain,
- populate Analysis cards.

### 2026-09-21 — DESKTOP-RECOMMENDED-XI-STRATEGIES — exact plan previews

Completed:
- Decision reports now serialize read-only current-GW lineup previews for the exact visible Best short-term, Best balanced and Best long-term transfer plans.
- Each preview applies only its already generated transfers, validates the resulting 15-player squad, then uses the existing `optimize_lineup` contract for the XI, bench order, captain and vice-captain.
- Squad now exposes Current XI plus the three matching strategy selectors. Selecting one updates only the preview pitch, OUT/IN bar, bench and captaincy card; it never writes account state or FPL data.
- Changing the decision run, projection run or loaded history clears every prior preview before a compatible report is installed. Historical reports without serialized matching previews stay explicitly unavailable.

Fixed:
- the unfinished preview bridge incorrectly used a post-transfer intermediate FT value of zero as the current-GW `SquadState`, causing `validate_squad` to reject legal one-transfer previews. The bridge now retains the current FT for lineup selection and preserves the engine's separately recorded next-GW rollover value.

Verified:
- focused decision, strategy-preview, transfer-plan and Run Center suite: 31 passed,
- changed-module Python compile check passed.

Next:
- review HOLD / free-transfer rollover policy separately before changing any transfer-candidate or ranking semantics.

### 2026-09-21 — DESKTOP-STRATEGIC-ACTION — V2 action presentation

Completed:
- added a prominent Analysis `Strategic action` card sourced only from the existing Optimizer V2 recommendation and its already serialized utility,
- Strategic Action keeps its V2 utility separate from the Greedy/V1 1/3/6-GW impact metrics,
- added the `Strategic` Squad preview alongside Short-term, Balanced and Long-term; it applies the exact V2 action in memory and uses the existing lineup optimizer for the XI, bench, captain and vice-captain,
- reframed the three horizon cards as `Transfer scenarios` with an explicit note that they rank projected squad impact and do not establish that a transfer beats V2's strategic ROLL decision,
- successful FPL sync now clears all preview/action state before applying the new account state.

Verified:
- focused Decision, strategy-preview, transfer-plan and Run Center tests: 33 passed,
- offscreen Analysis geometry passed at 1600x820, 1600x900 and 1900x1080,
- changed-module compile check passed.

Next:
- any change to HOLD exposure, default policy or free-transfer valuation requires a separate decision-policy milestone with historical validation.

## 2026-09-14 â€” DESKTOP-003C6E1 â€” Visual polish

Completed:
- added green checkbox styling aligned to brand green #167A3F,
- styled checked checkbox indicator for chip controls,
- strengthened visibility of the 'MY SQUAD' header,
- rebuilt root FPLControlCenter.exe.

Verified:
- GUI smoke passed,
- focused suite passed,
- full suite passed,
- frozen guard passed,
- EXE build/copy passed.

## 2026-09-14 â€” ASSETS-001B â€” Permanent FPL kit cache

Completed:
- confirmed official FPL kit pattern:
  `shirt_<team.code>-<size>.png`,
- confirmed sizes 66, 110 and 220,
- downloaded all 20 current team kits,
- preferred source size is PNG 220,
- stored local assets under:
  `desktop_app/assets/kits/2026-27/`,
- local filename contract:
  `team_<team_id>.png`,
- created `kit_manifest.json`,
- manifest maps FPL team ID and team code,
- SHA256 and image metadata stored per kit,
- created reusable refresh script:
  `scripts/fetch_fpl_kits.py`.

Important:
- GUI should use local cached kits,
  not download them on every launch,
- player -> kit mapping uses canonical FPL `team_id`,
- source `team.code` is retained for provenance.

Next:
- integrate cached kits into player cards,
- show Current XI plus 4-player bench,
- enlarge MY SQUAD rows,
- add pick-quality metrics,
- add next-3-GW score boxes 0â€“100,
- color scores red -> yellow -> green.

## 2026-09-14 â€” DESKTOP-003D1R2 â€” Real kits / bench completed

Completed:
- fixed MY SQUAD title initialization timing,
- MY SQUAD count now comes from persisted squad_state player_ids,
- retained official cached FPL kits for Current XI,
- retained four-player FPL-style bench,
- retained white X on green used-chip indicator,
- rebuilt one-file EXE with desktop assets.

Verified:
- XI cards = 11,
- XI official FPL kits = 11/11,
- bench cards = 4,
- bench official FPL kits = 4/4,
- MY SQUAD title = 15,
- checkbox X asset active,
- focused tests passed,
- full suite passed,
- frozen-engine guard passed,
- EXE build and root copy passed.

Next:
- visually verify Squad and Engine,
- then implement player pick metrics,
- add next-three-GW scores from 0 to 100,
- color upcoming fixture score tiles red -> yellow -> green.

## 2026-09-14 â€” DESKTOP-004A â€” Lineup and pitch orientation

Completed:
- Current XI remains 11 legal players,
- bench is derived as owned 15 minus active XI,
- removed XI/bench duplicates,
- correct current bench:
  Kelleher, Giles, Palmer, Evanilson,
- pitch row order changed to:
  FWD -> MID -> DEF -> GK -> BENCH,
- official FPL kit rendering preserved.

Verified:
- XI count = 11,
- bench count = 4,
- duplicates = 0,
- Current XI view passed,
- focused desktop tests passed,
- full test suite passed,
- frozen engine guard passed,
- one-file EXE rebuilt with assets.

Next:
- DESKTOP-004B:
  redesign Squad toward approved Premier League purple mockup,
  enlarge MY SQUAD,
  improve row spacing,
  translucent player cards,
  cleaner bench styling,
  global purple visual language.

## DESKTOP-004E3H OFFICIAL CURRENT XI

- Desktop `Current XI` now uses the official FPL entry picks from the previous completed gameweek instead of inferring the XI from the 15-player ownership list.
- `DesktopSquadState` persists `starting_player_ids` and `bench_player_ids`.
- For the current GW5 planning state, the source lineup is official GW4 picks for FPL entry `7940073`.
- Verified official XI: Sels; Maatsen, Justin, De Cuyper; GroĂź, Tavernier, B.Fernandes, Szoboszlai, Palmer; Calvert-Lewin, Haaland.
- Verified official bench order: Kelleher, Evanilson, Egan, Giles.
- GUI smoke verified 11 starters, 4 bench players and formation `1-3-5-2`.
- No GW5/V22 prediction run was performed as part of this desktop milestone.
- Full test suite and frozen baseline guard must pass before the packaged EXE is accepted.

<!-- DESKTOP-004E3H OFFICIAL CURRENT XI -->

## 2026-09-14 â€” DESKTOP CLEANUP / GUI CONSOLIDATION

Completed:
- replaced the historical `main_window.py` override stack with one stable desktop implementation,
- moved fixture display/probability lookup and local kit lookup into focused modules,
- retained the official persisted XI and ordered bench,
- retained exact Premier League branding, purple visual language, local outfield/GK kits, pitch markings, `p_5_plus` fixture badges and the right-side squad editor,
- implemented the pitch and centred bench entirely with Qt layouts and size policies,
- removed obsolete desktop patch runs, temporary previews/context files, backup/patch scripts, stale EXEs/specs and generated caches,
- rebuilt the sole root release artifact as `FPLControlCenter_PL.exe`.

Verified:
- desktop compile passed,
- focused desktop suite passed: 23 tests,
- responsive layout passed at 1600x820, 1600x900 and 1900x1080,
- exact XI/bench order, 33 XI badges, 12 bench badges, `p_5_plus` semantics and both goalkeeper kits passed,
- full suite passed: 1231 passed, 2 skipped,
- frozen-engine guard passed,
- packaged EXE startup smoke passed.

Next:
- generate a fresh production V22 GW5 projection only as a separate engine milestone,
- verify simulator/artifact completeness before connecting Decision Engine output.

## 2026-09-14 â€” DESKTOP VISUAL RECOVERY / QT-MATERIAL6

Completed:
- introduced one centralized desktop theme built on the pinned qt-material6 renderer with a project-owned Premier League light palette and QSS layer,
- restored the light header, readable context controls, segmented navigation, green painted pitch and field markings,
- restyled My Squad, Analysis, Engine and the Edit Squad drawer without reintroducing milestone override chains,
- made drawer visibility follow the active tab synchronously and kept it closed when returning to Squad,
- retained the official XI, ordered bench, local kits and existing `p_5_plus` fixture-badge semantics,
- added the desktop theme files to the PyInstaller bundle and rebuilt `FPLControlCenter_PL.exe`.

Verified:
- desktop compile passed,
- focused desktop suite passed: 23 tests,
- responsive layout passed at 1600x820, 1600x900 and 1900x1080,
- drawer navigation, pitch painting, exact XI/bench, fixture badges and goalkeeper kits passed,
- full suite passed: 1231 passed, 2 skipped,
- frozen-engine guard verified 17 files with zero mismatches,
- packaged EXE hash/copy and startup smoke passed.

Next:
- perform the user-facing visual review of the launched executable,
- keep fresh production V22 GW5 projection work as a separate engine milestone.

## 2026-09-14 â€” DESKTOP BENCH / INPUT CONTROL POLISH

Completed:
- removed the light outline from the specific `FPLBenchPanel` rule without changing Bench geometry or content,
- added compact rounded scrollbars and reserved arrow space for spin boxes, double spin boxes and combo boxes in the existing project QSS.

Verified:
- focused fixture/UI tests passed: 4 tests,
- four centred Bench cards and 12 fixture badges remain present,
- source application startup smoke passed,
- no model or data run was performed.

## 2026-09-14 â€” DESKTOP STEPPER / READ-ONLY SYNC RECOVERY

Completed:
- replaced the five native numeric spin boxes with one reusable `StepperField` based on `QLineEdit` and explicit minus/plus buttons,
- made the Bench panel fully opaque so pitch markings cannot show through it,
- added the `DISCONNECTED`, `LOGIN_REQUIRED`, `CONNECTING`, `SYNCING`, `CONNECTED` and `ERROR` account states,
- made the header action launch the dedicated persistent Edge CDP profile when login is required and become Retry sync after launch,
- added a shared post-sync completeness gate for IDs, personal prices, bank, FT, GW and official picks,
- identified the current 14/15 price gap as Bahoya (FPL element 648), retained as unknown until a successful account sync.

Verified:
- compile check passed,
- focused Stepper/account/UI suite passed: 17 tests,
- sync remains read-only and no token or credential persistence was added,
- rebuilt, copied and launched `FPLControlCenter_PL.exe`; packaged process responded successfully,
- frozen-engine guard verified 17 files with zero mismatches,
- no V22 run or model-data regeneration was performed.

## 2026-09-15 â€” DESKTOP LIVE SYNC ACCEPTANCE COVERAGE

Completed:
- verified the GUI login-required flow, managed Edge command/profile and retry-to-sync transition with no external FPL traffic,
- added a mocked successful-sync gate for 15 resolved players, 15/15 prices, bank, FT and official XI/bench,
- added an explicit read-only request test; account fetching uses GET only and has no transfer, chip, captain or vice-captain mutation path,
- left the rebuilt `FPLControlCenter_PL.exe` running for manual official-FPL login acceptance.

Verified:
- focused account-sync suite passed: 14 tests,
- no credentials or bearer tokens are persisted,
- no V22 run or model-data regeneration was performed.

## 2026-09-15 â€” DESKTOP DECISION ENGINE BRIDGE

Completed:
- connected the Analysis-tab Decision Engine button to the existing non-mutating `fpl_engine.shadow` runner and its existing Greedy 1GW / Optimizer V1 / Optimizer V2 contracts,
- runs the child process asynchronously with `IDLE`, `RUNNING`, `SUCCESS` and `ERROR` states and blocks duplicate starts,
- accepts only a complete, matching saved production projection bundle under `data/processed/predictions`; it never selects scratch artifacts or starts a new simulation,
- adapts the explicit desktop squad, personal purchase/selling prices, bank, FT and used-chip state into the existing optimizer contract without changing the saved account state,
- renders Greedy 1GW transfer or explicit ROLL output with supplied player, position, price, gain, horizon, hit, bank and decision-margin fields,
- writes local auditable decision reports under `data/processed/desktop_decisions` and verifies the runner reports no external mutations.

Verified:
- focused desktop-decision, shadow, orchestration and state suites: 24 passed,
- full suite: 1250 passed, 2 skipped,
- no V22 simulation, model-data regeneration, account mutation or Recommended XI implementation was performed.

Next:
- create and verify a matching fresh production projection artifact for the selected GW as a separate engine milestone,
- then connect the existing valid decision result to Recommended XI, captain and vice-captain presentation.

## 2026-09-15 â€” GW5 PRODUCTION V22 PROJECTION BUNDLE

Completed:
- materialized the canonical production GW5 projection run at `data/processed/predictions/2026-27/20260915T130524Z`,
- used the existing `predict-current` V22 pipeline with 10,000 simulations per fixture and deterministic seed 42,
- preserved the canonical production location; no scratch artifact is used by Desktop discovery,
- verified manifest season/GW, V22 simulator identity, fixture horizon, 659 player projections, provenance, expected minutes, expected points and probability fields,
- verified 15/15 owned-player coverage and projections for Haaland, Sels, Palmer and Evanilson with finite required values,
- verified the existing Desktop decision runner consumes the bundle and writes a read-only local report with `external_mutations: []`.

Important:
- The first attempted CLI invocation included the desktop `squad_state.json` as an optional shadow input.  That state has the desktop contract rather than the shadow `players` contract, so the run stopped after persistence before producing its final manifest.  The completed run intentionally omits that optional argument; the Desktop decision bridge performs the correct state adaptation itself.

Verified:
- focused current-pipeline, desktop-orchestration and desktop-decision suites: 20 passed,
- no V22/model logic, decision logic, GUI styling, account sync or squad state was changed,
- Recommended XI remains intentionally unimplemented.

Next:
- connect the already-valid decision result to Recommended XI, captain and vice-captain presentation as a separate desktop milestone.

## 2026-09-15 â€” DESKTOP RECOMMENDED XI PREVIEW

Completed:
- connected the existing Desktop Decision Engine report to the preview-only `Recommended XI` pitch view,
- validates the engine-supplied 15-player squad, transfer replacement, 2/5/5/3 composition, club limit, XI formation, captain, vice-captain and ordered four-player bench before rendering,
- uses only the matching canonical GW5 production bundle for player, kit and fixture-badge display data,
- renders the engine-provided captain, vice-captain, B1â€“B4 bench order and a subtle `IN` marker for incoming players,
- preserves the persisted current squad and Current XI; switching views only changes the pitch preview.

Verified:
- focused desktop decision/state/orchestration suite: 19 passed,
- production smoke test loaded the actual GW5 V22 bundle and compatible decision report, then switched Recommended XI to Current XI successfully,
- no V22 run, decision-engine logic change, account mutation or chip-screen implementation was performed.

Next:
- Chip Screen remains the next separately scoped desktop decision presentation task.

## 2026-09-15 â€” DESKTOP CHIP SCREEN BRIDGE

Completed:
- connected the Analysis-tab Chip Screen button to the existing read-only chip-screen and timing-policy contracts,
- requires the matching canonical production bundle and a compatible, read-only Desktop decision report,
- runs the child process asynchronously with `IDLE`, `RUNNING`, `SUCCESS` and `ERROR` states and blocks duplicate or conflicting engine runs,
- uses the existing deterministic V2 candidate generator to provide the bounded candidate universe for the existing exact Free Hit/Wildcard screen,
- renders the supplied chip recommendation, incremental EV when available, policy reason, horizon and account-derived available chips,
- preserves account state and rejects any report that claims an external mutation.

Verified:
- focused desktop chip, decision, state and orchestration suites: 26 passed,
- compile check passed,
- no V22 run, model/data change, account mutation or Full GW Analysis implementation was performed.

Next:
- Full GW Analysis remains the next separately scoped desktop workflow.

## 2026-09-15 â€” CHIP SCREEN EXACT PATH PROFILE

Measured:
- the Free Hit/Wildcard MILP portfolio solve is not the dominant cost (about 0.02s for one GW5 solve with 101 candidates),
- exact autosub scoring dominates: a single exact fixed-squad GW5 evaluation profiled at about 26.5s before the structural cache,
- the hot path was repeated legal bench selection during 3,300 autosub evaluations per exact squad.

Completed:
- added a structural-only autosub selection cache keyed by bench positions, appearance mask and positional DNP state; it never stores player EV, season, GW or account state,
- added child-process progress stages for loading, candidate generation, exact chip stages and final comparison.

Verified:
- focused desktop chip and existing chip-screen/timing suites: 14 passed,
- compile check passed.

Current limitation:
- the full exact GW5 Free Hit/Wildcard portfolio remains too slow for an interactive completion target because it evaluates up to 16 candidate squads, with Wildcard scoring six gameweeks per squad.  Full GW Analysis remains blocked pending an exact autosub evaluator optimization that reduces repeated lineup/bench enumeration without changing output semantics.

## 2026-09-15 â€” DESKTOP FULL GW ANALYSIS

Completed:
- connected the existing production-bundle validation, Decision Engine, Recommended XI preview and Chip Screen into one read-only asynchronous workflow,
- reuses only a matching saved production bundle and reports a clear prerequisite error instead of starting V22 or using scratch data,
- renders transfer and Recommended XI results before the long-running exact Chip Screen finishes,
- reports `VALIDATING`, `PROJECTIONS`, `DECISION`, `RECOMMENDED_XI`, `CHIP_SCREEN`, `COMPLETE`, `PARTIAL` and `ERROR` states,
- added cooperative Chip Screen cancellation through the existing child `QProcess`; it never alters account state and retains completed decision/XI results,
- added retry for a cancelled or failed Chip Screen.

Verified:
- focused desktop full-analysis, chip, decision and orchestration suites: 29 passed,
- full suite: 1267 passed, 2 skipped,
- no V22 run, model/data change, account mutation or chip-semantic change was performed.

Next:
- final GUI cleanup and user documentation; do not add new desktop features without a separate scoped milestone.

## 2026-09-15 â€” DESKTOP RELEASE ACCEPTANCE

Completed:
- verified the source desktop launch, maximized entry point, production GW5 bundle discovery and the automated layout contract at 1600Ă—820, 1600Ă—900 and 1900Ă—1080,
- retained the current GUI implementation because no clear duplicate desktop implementation, obsolete active production patch method or visual regression was found,
- added the practical Polish user guide at `docs/USER_GUIDE_PL.md`, including read-only FPL safety, normal GW workflow, partial analysis and exact-chip duration behaviour,
- built a clean windowed `dist/FPLControlCenter_PL.exe` with the Premier League icon and bundled desktop assets; the release executable launched successfully.

Verified:
- desktop-focused suite passed,
- full suite: 1267 passed, 2 skipped,
- frozen V1 baseline guard passed,
- Python compile check passed,
- no V22 run, model/data change, account mutation or chip-semantic change was performed.

Release note:
- an already-running older root `FPLControlCenter_PL.exe` held the root release filename open, so the verified new executable remains at `dist/FPLControlCenter_PL.exe` until that running instance is closed and the file can be copied safely.

Packaging correction:
- the first release bundle omitted the dynamically imported `qt_material6` package and `desktop_app/styles`; both are now included in the final PyInstaller specification,
- the final windowed executable launches with the `FPL Control Center` window title, the PL icon and bundled desktop assets.

## 2026-09-15 â€” DESKTOP ENGINE SIMULATION LIMIT

Completed:
- increased only the Engine `Simulations / fixture` StepperField maximum from 10,000 to 50,000; default 256, step 64 and Seed are unchanged.

Verified:
- focused StepperField suite: 5 passed,
- boundary regression confirms 50,000 is accepted and 50,001 clamps to 50,000.

## 2026-09-15 â€” DESKTOP CAPTAINCY CARD WIRING

Completed:
- connected the Analysis Captaincy card to the captain and vice-captain already validated for the Recommended XI,
- renders existing player names plus fixture, expected points and `p_5_plus` when the production fixture display supplies them,
- clears stale captaincy content at the beginning of every new Decision/Full GW run,
- remains preview-only and never writes to FPL account state.

Verified:
- focused desktop decision and Full GW Analysis suites: 19 passed.

Next:
- final user visual acceptance and root EXE replacement after the existing desktop instance is closed; then documentation-only maintenance.


## 2026-09-16 â€” DECISION BUNDLE SIMULATION-COUNT GATE

Completed:
- removed the obsolete Decision Engine rejection of a canonical bundle solely because its recorded simulation count is not 10,000,
- accepts recorded integer counts from 1 through 50,000,
- verifies bundle, prediction context and run manifest season/GW identity,
- verifies bundle and manifest simulation counts match before a desktop decision runs,
- retains canonical-path selection and rejects scratch paths from the desktop selector.

Verified:
- changed-module compile check passed,
- focused shadow, desktop-decision, current-pipeline and market-contract suite: 48 passed,
- the existing canonical 25,000-simulation GW5 bundle passed the new gate; its recorded mode remains `NON-PRODUCTION DIAGNOSTIC`.

Important:
- bookmaker integration remains a non-production shadow challenger. No selected, historically validated production blend policy or second production simulation path exists in the checked source, patch backups or archived market artifacts.

## 2026-09-16 â€” CURRENT-GW MARKET SHADOW COLLECTION

Completed:
- added a post-V22, forward-looking Market Shadow collector that is isolated from production projections and decision inputs,
- uses The Odds API event discovery, maps only current-GW FPL fixtures, then makes at most one player-props request per mapped fixture,
- reuses the existing HttpCache and RawStore contracts and reuses only a fresh completed timestamped shadow artifact on retry; stale artifacts receive a new non-overwriting retry filename,
- persists non-overwriting JSON evidence under `data/processed/market_shadow/<season>/<production_run_id>/market_shadow.json`,
- records provider, timestamps, raw snapshot receipt where available, quota headers, identity/player coverage, normalized probabilities, all five existing blend candidates and explicit `production_influence: false`,
- records unavailable credentials, missing EPL props and provider failures as SKIPPED/FAILED without invalidating V22,
- links only non-influential shadow status metadata into the production run manifest; the decision bundle remains untouched.

Verified:
- changed-module compile check passed,
- focused Market Shadow, Odds API, current pipeline and desktop-decision suites: 53 passed,
- no live bookmaker request, V22 rerun, EXE build or account mutation was performed.

Expected normal usage:
- a ten-fixture GW performs one cached event-discovery request plus at most ten cached player-props requests; all five candidate weights reuse each fixture response.

- artifact provenance also includes the original V22 model/simulator versions, simulation count, base seed and seed strategy from the already persisted production manifest.

## 2026-09-16 — CURRENT-GW MARKET SHADOW PIT / IDENTITY RECOVERY

Completed:
- separated immutable V22 `model_prediction_timestamp` from `market_snapshot_timestamp` and the new `shadow_prediction_timestamp`,
- retains strict quote `<= shadow_prediction_timestamp` and pre-kickoff checks; post-kickoff fixtures are explicitly rejected,
- stores each new Shadow observation under a timestamped non-overwriting artifact name and does not modify the V22 bundle or run manifest,
- added closed, explicit Premier League provider-name aliases, still requiring matching home/away sides and kickoff before a fixture maps,
- records concrete mapping status/reason per canonical fixture.

Verified:
- focused Market Shadow, Odds API, current pipeline and desktop-decision tests: 55 passed,
- real GW5 smoke on the existing 25k V22 bundle: 10/10 fixtures mapped, 1,958 PIT-usable props and 298/659 player-fixture market priors,
- the V22 run-manifest SHA-256 was unchanged; `production_influence: false` remains enforced.

Next:
- retain Market Shadow as a non-production challenger pending separate evaluation; do not build or change the desktop release without explicit approval.

## 2026-09-17 — CHIP-STRATEGY-001 — Season-aware strategic chip horizon

Completed:
- exact Chip Screen horizon is capped at the active chip-period boundary: GW1–19 or GW20–38,
- later-GW strategic scan runs as a separate model-only 3,000-simulation-per-fixture materialization with `--skip-market-shadow`,
- strategic FH/WC uses the existing unlimited-squad MILP base plan and one existing exact evaluation; the full near-term candidate portfolio remains exclusive to the exact screen,
- strategic results are cached per production bundle/GW under `data/interim/desktop_chip_strategy/` and are advisory only,
- Chip Strategy UI now distinguishes the exact near-term recommendation from a materially stronger later strategic estimate using the existing timing tolerance.

Verified:
- focused chip, policy and desktop summary suite: 29 passed,
- no projections, bookmaker calls, EXE build, or account mutations were made during verification.

Next:
- manually run Chip Screen against a valid production bundle when a live strategic horizon is needed.

## 2026-09-17 — DESKTOP-TARGETS-001 — Read-only Top Player Targets

Completed:
- added a compact, position-filterable Top Player Targets list below the existing Recommended Transfers card,
- sources only the selected canonical production bundle and adjacent player/fixture display data,
- excludes owned and explicitly unavailable players and ranks deterministically with the existing V2 `weighted_ev_next_6` value,
- marks the existing optimizer-selected incoming player when it is present in the informational list,
- keeps the list read-only: it does not invoke projections, alter Decision Engine output, or write squad/account state.

Verified:
- changed-module compile check passed,
- focused Top Player Targets and Desktop Decision suites: 20 passed.

Next:
- Run Center/history selection remains a separate UI milestone.

## 2026-09-17 — DESKTOP-RUN-CENTER-001 — Canonical run and analysis history

Completed:
- added an Analysis-tab Run Center that discovers only complete, canonical production bundles compatible with the active season and GW,
- stores the selected projection bundle for the desktop session; Decision Engine, Recommended XI, Chip Screen and Full GW Analysis validate and use that exact bundle,
- added small canonical Full GW Analysis manifests under `data/processed/desktop_analyses/<season>/`, referencing existing decision/chip reports and a compact local squad-state snapshot,
- loading COMPLETE or PARTIAL history restores transfer, target, XI, captaincy and available chip output without starting models, V22, Chip Screen, FPL sync or bookmaker work,
- blocks report/projection mismatches rather than mixing artifacts.

Verified:
- changed-module compile check passed,
- focused Run Center, Decision, Full Analysis, Top Targets and orchestration suites: 42 passed.

Next:
- final build remains a separate release task.

## 2026-09-17 — RELEASE-001 — Run Center desktop release

Completed:
- built the windowed one-file `FPLControlCenter_PL.exe` from the canonical spec,
- verified packaged Run Center, captaincy, qt-material, assets/styles and Market Shadow source payloads,
- verified both dist and root executable open a responsive `FPL Control Center` main window,
- copied the accepted dist executable to the repository root with matching SHA-256.

Verified:
- final executable: 70,300,161 bytes,
- SHA-256: `C86B22D62F20A7124AFDD586569A2F167320E5D88B4887C0AB521FE53343B630`,
- no projections, FPL sync, decision/chip work, V22 run or bookmaker request was made during release verification.

## 2026-09-17 — CHIP-STRATEGY-002 — Active-half pruning and strategic range correction

Completed:
- chip availability is resolved from the explicit account `ChipState` before exact or strategic chip-specific evaluation; unavailable first-half chips are never ranked, evaluated, or emitted as `evaluating` progress,
- GW5 with first-half Wildcard used evaluates only Free Hit, Bench Boost and Triple Captain; the second-half Wildcard remains unavailable until GW20,
- strategic materialization starts at the strategic range rather than the current GW: GW5 uses GW11–GW19, requesting a nine-GW model-only bundle with `--skip-market-shadow`,
- strategic cache identity now records the requested start GW and exact gameweek list, preventing reuse of the old GW5–GW19 / 15-GW bundle,
- strategic input retains explicit squad/account state while accepting the separate strategic bundle's own timestamp and gameweek contract,
- prerequisite failures now report the concrete reason before a 3,000-simulation strategic projection is launched.

Verified:
- changed-module compile check passed,
- focused chip screen, exact scorer, timing, strategy and desktop chip suite: 37 passed,
- existing GW5 fixture horizon confirms 150 former fixtures for GW5–GW19 versus 90 required fixtures for GW11–GW19,
- existing small/current bundle benchmark: used-Wildcard exact screen completed in 92.85 seconds with zero Wildcard candidates; the pre-fix all-chip reference exceeded 367 CPU seconds before the intentionally stopped measurement.

Next:
- no further Chip Screen optimization in this milestone; run the corrected strategic materialization only when a fresh strategic result is explicitly needed.

## 2026-09-18 — DESKTOP-ANALYSIS-TRANSFER-PLANS — Feasible transfer comparison

Completed:
- the Analysis tab now gives the existing engine recommendation the primary, wide readable area and shows up to two additional existing Optimizer V1 candidate plans beneath it,
- the desktop only renders plan data already calculated by the optimizer: transfers, free-transfer use, hit, bank after, net gain and 1/3/6-GW projection impacts; it does not rank, repair or invent plans,
- optimizer alternatives now carry their already calculated economic fields and projection-impact deltas through the existing decision report contract,
- Top player targets remains a separate informational weighted-6-GW table, now with combined player/club search and position filtering plus read-only `AFFORDABLE`, `NEEDS FUNDING` and `OWNED` status,
- the Recommended XI remains tied solely to the primary engine recommendation; alternative plans cannot alter the preview or account state.

Verified:
- changed-module compile check passed,
- focused optimizer, shadow-report, desktop decision, transfer-plan, transfer-target and Full GW Analysis suite: 51 passed,
- offscreen 1600x820 geometry check verifies the transfer plan card is wider than the Captaincy card, the summaries retain their minimum readable height and the targets table remains scrollable.

Next:
- build a desktop release only when explicitly requested.

## 2026-09-22 — DESKTOP-STRATEGIC-PLANNER-V3 — Three-GW challenger

Completed:
- added a separate, read-only Strategic Planner V3 that searches three sequential Gameweeks with bounded beam search, legal squad/transfer handling, FPL free-transfer rollover, selling-price/bank accounting, hit costs and existing lineup optimisation,
- records both the best unrestricted path and a forced-HOLD-now counterfactual in the same V3 objective units; terminal free-transfer option value is explicitly separate from projected lineup points,
- added an optional, provenance-checked price-signal contract which reports future affordability risk only and never changes points or player prices,
- preserved V2 as a diagnostic field, while V3 Analysis and preview handling report an explicit V3-unavailable state rather than silently substituting V2,
- added the Strategic Planner V3 and If you roll Analysis cards; Current XI now hides the transfer bar completely and the existing Top Targets field retains its compact unlabeled search control.

Verified:
- changed-module compile check passed,
- focused V3, decision, strategy-preview, transfer-target, desktop layout, Full GW, Run Center, Chip, deadline and transfer-plan suites: 76 passed,
- local current-bundle V3 benchmark completed without network calls: beam width 40, 91 expanded states, 2,161 candidate actions, 18.05 s; existing lineup evaluation is the dominant cost.

Known:
- a full current `run_desktop_decision` benchmark remains dominated by the pre-existing V2 shadow path; it was not changed by this challenger milestone and V3 stays independently callable/tested.

Next:
- source acceptance, then build a desktop release only when explicitly requested.

## 2026-09-21 — DESKTOP-ANALYSIS-ACTIONABLE-GW — Analysis readability and live GW guard

Completed:
- widened the Season selector so the complete `2026/27` value is readable,
- added a local-only official-event deadline resolver that reads the latest valid cached FPL bootstrap RawStore payload; the live GW selector advances to the first deadline that has not passed on startup and after account-state refresh,
- removed nested scroll areas from Transfer scenarios, Captaincy and Chip strategy; the outer Analysis page now owns scrolling and the targets table grows to every rendered row without inner scrollbars,
- made Best short-term, Best balanced and Best long-term independently select the maximum existing comparable 1/3/6-GW impacts, including valid repeated plans,
- made Current XI clear transfer markers and owned-player OUT state, and made recommendation fixture badges begin at the selected analysis GW.

Verified:
- changed-module compile check passed,
- focused deadline, strategy-preview, horizon-plan, target-table and desktop geometry suite: 25 passed,
- focused Decision Engine, Full GW Analysis, Run Center and Chip suite: 45 passed,
- all GUI verification used `QT_QPA_PLATFORM=offscreen`; no projection, FPL sync, market call or account mutation was performed.

Next:
- build a desktop release only when explicitly requested.

## 2026-09-18 — RELEASE-ANALYSIS-HORIZONS — Desktop release

Verified:
- built the canonical windowed one-file `FPLControlCenter_PL.exe` with the horizon-ranked Analysis plans and six-GW fixture target table,
- accepted the dist executable after a cold start opened the `FPL Control Center` main window and closed cleanly, then copied the exact artifact to the repository root,
- root and dist artifacts match: 70,321,450 bytes, SHA-256 `51F53DA08811417904CF91F410F1A6956246120B6A44CEECD02B951F571EE9F8`.

Next:
- no release action is required until another explicitly requested desktop change.

## 2026-09-18 — RELEASE-ANALYSIS-CARDS — Desktop release

Verified:
- built the canonical windowed one-file `FPLControlCenter_PL.exe` with the redesigned Analysis presentation, all current desktop modules, styles, assets, PL icon, Run Center, captaincy and Market Shadow payloads,
- accepted the dist executable after a cold start opened the `FPL Control Center` main window and closed cleanly, then copied the exact verified artifact to the repository root,
- root and dist artifacts match: 70,320,712 bytes, SHA-256 `E6ABCAE41B21966338D2CFDF71D6C0A6B626EDD675AB8C2FD13E48C0965C2BBF`.

Next:
- no release action is required until another explicitly requested desktop change.

## 2026-09-18 — DESKTOP-ANALYSIS-HORIZONS — Comparable transfer plans and 6-GW fixtures

Completed:
- Analysis now presents up to three distinct, already engine-validated plans as Best short-term, Best balanced and Best long-term, ranked respectively by the comparable transfer-impact deltas for 1, 3 and 6 GW,
- removes source-specific projected-gain prominence and the cross-source `vs recommended` comparison; cards highlight only their selected comparable horizon impact alongside all 1/3/6-GW impacts,
- preserves existing Greedy and Optimizer V1 candidates, all existing feasibility gates, the current Recommended XI behavior and read-only account safety; legacy history reports without impact fields render one clearly labelled non-comparable current-decision card,
- Top player targets now displays a compact ordered `Fixtures (6GW)` field sourced from the existing fixture repository, while retaining search, position filtering, ranking and affordability status.

Verified:
- changed-module compile check passed,
- focused transfer-plan, transfer-target, desktop decision, Full GW Analysis, chip and Run Center suite: 55 passed,
- offscreen layout checks continue to pass at 1600x820, 1600x900 and 1900x1080.

Next:
- build a desktop release only when explicitly requested.

## 2026-09-18 — RELEASE-ANALYSIS-TRANSFER-PLANS — Desktop release

Verified:
- rebuilt the canonical windowed one-file `FPLControlCenter_PL.exe` with the Analysis transfer-plan presentation modules, targets table, Run Center, captaincy, Market Shadow payloads, assets, styles, `qt_material6` and PL icon,
- accepted the dist executable after it opened a `FPL Control Center` main window and closed cleanly, then copied that exact binary to the repository root,
- root and dist artifacts match: 70,313,536 bytes, SHA-256 `F58BE9597A806EA3F0F17C8B07A21643E4F853F0BE0F4BC947FB7EBF0916AD10`.

Next:
- no release action is required until another explicitly requested desktop change.

## 2026-09-18 — DESKTOP-ANALYSIS-CARDS — Structured Analysis dashboard

Completed:
- redesigned the Analysis tab presentation around a compact Run Center, a wide card-based transfer-plan comparison, stacked Captaincy and Chip Strategy detail cards, and a larger scrollable Top player targets table,
- Plan 1 is visually primary; the existing Optimizer V1 alternatives remain secondary cards and expose only already calculated transfers, FT use, hit, bank, projected gain, 1/3/6-GW impacts, funding released and comparison fields,
- moved the existing analysis actions into Run Center and removed its redundant introductory header, preserving all actions while giving the targets table more usable vertical space,
- normalized transfer-summary separators to `|` and `—`, removing the literal `?` separator issue,
- retained the existing production bundle target ranking, player/club search, position filter and read-only affordability status; no data, account, model, decision, chip, captaincy or Market Shadow contract changed.

Verified:
- changed-module compile check passed,
- focused transfer-target, desktop decision, Full GW Analysis, chip and Run Center suite: 52 passed,
- offscreen checks passed at 1600x820, 1600x900 and 1900x1080; the primary plan area remains wider than the side cards and both plan/detail views use scroll containers rather than clipping content.

Next:
- build a desktop release only when explicitly requested.

## 2026-09-22 — DESKTOP-STRATEGIC-V3-EDGE-AUDIT — Preview identity and terminal FT correction

Completed:
- serialized an independent, order-insensitive transfer identity for each `short_term`, `balanced` and `long_term` preview slot; duplicate Short-term/Balanced transfer sets remain valid while a Long-term preview cannot be borrowed from another slot,
- corrected final-beam pruning in Strategic Planner V3 to include the existing terminal FT option value before retaining the final beam, so every retained final action is compared in the documented total V3 objective units,
- added an explicit four-GW diagnostic-only configuration gate; the production default remains three GW with unchanged beam settings and objective.

Verified:
- the supplied 20260922 decision report has matching displayed and serialized previews for Short-term, Balanced and Long-term,
- current-bundle edge audit: the former GW8 Kelleher -> Raya candidate gained 0.55 projected lineup points but lost 1.00 terminal FT value, a net -0.45 V3 objective contribution; the corrected three-GW path holds instead,
- focused V3, desktop decision, preview and transfer-plan suite: 34 passed; compile passed; no network, V22 rerun, account mutation or EXE build.

Next:
- source acceptance, then a desktop release only when explicitly requested.

## 2026-09-22 — DESKTOP-V3-ROLL-PANEL — Later transfer visibility

Completed:
- the If you roll panel now reads the already computed forced-HOLD V3 path and, when next GW is HOLD, displays the first later transfer with GW, OUT/IN, FT transition and bank;
- it shows an explicit no-transfer-within-horizon message when every remaining action is HOLD and does not duplicate an immediate next-GW transfer.

Verified:
- focused desktop decision and strategy-preview suite: 25 passed; compile passed;
- no planner run, external call, account mutation or EXE build was performed.

Next:
- source acceptance, then a desktop release only when explicitly requested.

## 2026-09-22 — RELEASE-STRATEGIC-V3-ROLL-PANEL — Desktop release

Verified:
- rebuilt the canonical windowed one-file `FPLControlCenter_PL.exe` from the current spec, assets, styles and PL icon,
- the dist artifact opened a responsive `FPL Control Center` main window after onefile extraction and closed through a normal close request,
- copied the verified dist artifact to the repository root and repeated the launch/normal-close check,
- root and dist artifacts match: 70,339,384 bytes, SHA-256 `DCC726E0FF4F80520645AF7ADE9F74E0369CC20C9E9E2EFBB38A334002A17DDA`.

Next:
- no release action is required until another explicitly requested desktop change.

## 2026-09-25 — ROADMAP-P2.1 — Player Availability & Minutes Risk V1

Completed:
- added a typed, immutable, advisory-only `PlayerAvailabilitySnapshot` carrying official FPL availability/status/news provenance and distinct minutes-risk evidence;
- enforces point-in-time boundaries for official metadata, news, and completed-fixture minutes; unavailable recent-minute sequences remain explicit unknowns;
- attaches the context-bound snapshot to `DecisionInput` as policy-inaccessible advisory data, persists it under `data/processed/player_availability_snapshots/<projection_run_id>/`, and references it from typed decision reports and replay archives;
- added a compact Analysis risk card and optional trust note without changing V22, transfer policies, captaincy, chip logic, or account state.

Verified:
- local accepted-bundle diagnostic created a referenced immutable snapshot for 26 relevant players: official-status coverage 100%, recent-minute-sequence coverage 0%, and `production_influence=false`;
- focused availability, report-schema, replay, trust, and desktop-decision suite: 62 passed; changed-module compile check passed; no provider calls or account mutation.

Next:
- acquire point-in-time completed-fixture minute sequences before treating minutes risk as more than an explicitly unknown advisory signal; no build is required unless a desktop release is requested.

## 2026-09-26 — ROADMAP-P2.2 — Point-in-time player minutes history

Completed:
- added immutable advisory-only completed-fixture player-minute history snapshots with strict source/outcome availability and kickoff cutoff checks; fixture ID is primary so DGWs are retained independently and BGWs are not invented,
- saves companion artifacts under data/processed/player_minutes_history_snapshots/<projection_run_id>/, carries SHA-256 references in DecisionReportV2 and Replay Archive, and feeds only existing Player Availability Risk advisory evidence,
- desktop decision runs use only an explicitly retained local sidecar; absent evidence creates an explicit UNAVAILABLE snapshot and never triggers an external fetch.

Verified:
- local diagnostic for 20260921T204826Z requested 26 relevant players and found 0 safe completed appearances; the immutable diagnostic snapshot is UNAVAILABLE.

Next:
- acquire timestamped local Official FPL element-summary/finished-fixture snapshots through an explicit refresh path before treating minutes risk as calibrated evidence.

## 2026-09-26 — ROADMAP-P2.3 — Official FPL player-history acquisition

Completed:
- added the explicit, read-only refresh-player-history CLI command using existing OfficialFPLAdapter, five-minute configurable HttpCache and RawStore; it is never called by desktop startup, report loading or replay,
- uses the per-player official element-summary/<player_id>/ endpoint plus official fixture completion state, deduplicates squad/decision/captain/top-target candidates, saves immutable acquisition receipts beside a canonical bundle, and retains raw snapshot/checksum/cache/observed-time provenance,
- P2.2 consumes only receipts observed no later than the PlanningContext cutoff, leaving post-deadline refresh data retained but ineligible for an older decision.

Verified:
- one explicit current acquisition requested 28 players, made 29 Official FPL requests, produced 140 history rows over 42 fixtures with 0 failures, and saved player_minutes_history_records_527d7b879919d1578d17099b.json; its 2026-09-26 observation is correctly rejected for the existing 2026-09-21 GW6 PlanningContext.

Next:
- execute the explicit refresh before a future official deadline and then run a new decision to obtain calibrated, decision-time recent-minutes evidence; no desktop build is required until explicitly requested.


## 2026-09-26 - ROADMAP-P2.4 - Automatic pre-deadline advisory capture

Completed:
- Run new analysis passes an opt-in flag to the external Decision worker only; startup, loading and replay remain acquisition-free.
- after Greedy/V1/V2/V3 and preview freeze, the worker deduplicates the current squad, decision paths, previews/captaincy and ten current targets, then applies a deadline gate before constructing Official FPL transport.
- eligible capture reuses the P2.3 adapter/cache/RawStore service and writes immutable advisory minutes/availability snapshots before final DecisionReport serialization.
- a pre-deadline advisory capture has its own recorded cutoff; it is context-bound but does not alter the PlanningContext or any policy output. Archive validation preserves this separate pre-deadline boundary.
- post-deadline or unknown-deadline runs skip provider access explicitly; acquisition failure remains advisory.

Next:
- the next real pre-deadline Run new analysis can accumulate valid Official FPL advisory evidence automatically. No EXE build is required until explicitly requested.
