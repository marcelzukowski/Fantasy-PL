from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from shutil import copy2


# Windows PowerShell can expose a legacy console encoding
# such as cp1250 to subprocesses.  The sync output contains
# currency symbols and player names, so force UTF-8 explicitly.

if hasattr(
    sys.stdout,
    "reconfigure",
):

    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace",
    )


if hasattr(
    sys.stderr,
    "reconfigure",
):

    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace",
    )


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(ROOT),
    )


from playwright.sync_api import (
    Error as PlaywrightError,
    sync_playwright,
)

from desktop_app.data_access import (
    load_players,
    resolve_player_source,
)

from desktop_app.fpl_account import (
    FPLAccountError,
    account_state_issues,
    apply_account_snapshot,
    fetch_my_team,
    snapshot_from_my_team,
)

from desktop_app.state import (
    DesktopStateError,
    load_state,
    save_state,
    validate_state,
)


CDP_URL = (
    "http://127.0.0.1:9222"
)

FPL_ROOT = (
    "https://fantasy.premierleague.com"
)

MY_TEAM_URL = (
    FPL_ROOT
    + "/my-team"
)

STATE_PATH = (
    ROOT
    / "data"
    / "user"
    / "squad_state.json"
)

BACKUP_PATH = (
    ROOT
    / "scratch"
    / "desktop"
    / "desktop003b3_cdp_sync"
    / "squad_state_before_sync.json"
)


MY_TEAM_PATTERN = re.compile(
    r"/api/my-team/(\d+)/?"
)


print()
print("=" * 78)
print("DESKTOP-003B3B EDGE SESSION SYNC")
print("=" * 78)

print()
print("browser mode             : existing Edge")
print("FPL account access       : READ ONLY")
print("transfers executed       : NO")
print("chip changes             : NO")
print("captain changes          : NO")
print("token printed            : NO")
print("token saved              : NO")


# ============================================================
# LOCAL STATE
# ============================================================

if not STATE_PATH.exists():

    raise SystemExit(
        "Missing data/user/squad_state.json"
    )


try:

    old_state = load_state(
        STATE_PATH
    )

except Exception as exc:

    print()
    print(
        "LOCAL STATE LOAD: FAIL"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    raise SystemExit(
        11
    )


BACKUP_PATH.parent.mkdir(
    parents=True,
    exist_ok=True,
)

copy2(
    STATE_PATH,
    BACKUP_PATH,
)


print()
print("=== LOCAL STATE BEFORE SYNC ===")

print(
    "season:",
    old_state.season,
)

print(
    "gameweek:",
    old_state.gameweek,
)

print(
    "players:",
    len(
        old_state.player_ids
    ),
)

print(
    "bank:",
    f"£{old_state.bank_tenths / 10:.1f}m",
)

print(
    "free transfers:",
    old_state.free_transfers,
)

print(
    "selling prices:",
    len(
        old_state.selling_prices_tenths
    ),
)


# ============================================================
# PLAYER MAP
# ============================================================

player_source = (
    resolve_player_source(
        ROOT
    )
)

players = load_players(
    player_source
)


provider_count = sum(
    player.provider_id
    is not None
    for player
    in players.values()
)


print()
print("=== PLAYER MAP ===")

print(
    "source:",
    player_source,
)

print(
    "provider IDs:",
    f"{provider_count}/{len(players)}",
)


if provider_count != len(
    players
):

    print(
        "PLAYER MAP: FAIL"
    )

    raise SystemExit(
        12
    )


# ============================================================
# CONNECT TO EXISTING EDGE
# ============================================================

captured = {
    "token":
        None,

    "entry_id":
        None,
}


def inspect_request(
    request,
):

    url = str(
        request.url
    )


    match = MY_TEAM_PATTERN.search(
        url
    )


    try:

        headers = request.headers

    except Exception:

        headers = {}


    auth = (
        headers.get(
            "x-api-authorization"
        )
        or headers.get(
            "authorization"
        )
    )


    if (
        auth
        and auth.casefold().startswith(
            "bearer "
        )
    ):

        token = auth[
            7:
        ].strip()


        if token:

            captured[
                "token"
            ] = token


    if match:

        captured[
            "entry_id"
        ] = int(
            match.group(
                1
            )
        )


print()
print("=== EDGE CONNECTION ===")


try:

    with sync_playwright() as p:

        try:

            browser = (
                p.chromium
                .connect_over_cdp(
                    CDP_URL
                )
            )

        except PlaywrightError as exc:

            print(
                "EDGE CDP CONNECTION: FAIL"
            )

            print(
                "Could not connect to "
                "localhost:9222."
            )

            print(
                "Keep the special Edge window "
                "open and do not start a "
                "different Edge instance."
            )

            raise SystemExit(
                21
            )


        print(
            "EDGE CDP CONNECTION: PASS"
        )


        contexts = browser.contexts


        if not contexts:

            print(
                "EDGE CONTEXT: FAIL"
            )

            raise SystemExit(
                22
            )


        context = contexts[
            0
        ]


        context.on(
            "request",
            inspect_request,
        )


        fpl_pages = [
            page
            for page
            in context.pages
            if (
                "fantasy.premierleague.com"
                in page.url
            )
        ]


        if fpl_pages:

            page = fpl_pages[
                0
            ]

        else:

            page = context.new_page()


        print(
            "FPL PAGE:",
            page.url,
        )


        print()
        print(
            "Refreshing My Team to capture "
            "authenticated API traffic..."
        )


        try:

            page.goto(
                MY_TEAM_URL,
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=60000,
            )

        except Exception:

            pass


        deadline = (
            time.monotonic()
            + 45
        )

        reload_at = (
            time.monotonic()
            + 5
        )


        while (
            (
                captured[
                    "token"
                ]
                is None
                or captured[
                    "entry_id"
                ]
                is None
            )
            and time.monotonic()
            < deadline
        ):

            page.wait_for_timeout(
                500
            )


            if (
                time.monotonic()
                >= reload_at
            ):

                try:

                    page.reload(
                        wait_until=(
                            "domcontentloaded"
                        ),
                        timeout=30000,
                    )

                except Exception:

                    pass


                reload_at = (
                    time.monotonic()
                    + 7
                )


        token = captured[
            "token"
        ]

        entry_id = captured[
            "entry_id"
        ]


        print()
        print(
            "AUTH TOKEN CAPTURE:",
            (
                "PASS"
                if token
                else "FAIL"
            ),
        )

        print(
            "token value:",
            (
                "[HIDDEN]"
                if token
                else "NONE"
            ),
        )

        print(
            "ENTRY ID CAPTURE:",
            (
                "PASS"
                if entry_id
                else "FAIL"
            ),
        )


        if entry_id:

            print(
                "entry id:",
                entry_id,
            )


        if (
            token is None
            or entry_id is None
        ):

            print()
            print(
                "Authenticated my-team "
                "request was not detected."
            )

            print(
                "Local state was NOT changed."
            )

            raise SystemExit(
                23
            )


        # Important:
        # Do NOT browser.close().
        # This is the user's normal Edge.


except SystemExit:

    raise


except Exception as exc:

    print()
    print(
        "EDGE SESSION CAPTURE: FAIL"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    raise SystemExit(
        24
    )


# ============================================================
# FETCH PRIVATE MY-TEAM DATA
# ============================================================

print()
print("=== AUTHENTICATED MY-TEAM ===")


try:

    payload = fetch_my_team(
        entry_id=entry_id,
        bearer_token=token,
    )


except FPLAccountError as exc:

    print(
        "MY TEAM FETCH: FAIL"
    )

    print(
        str(exc)
    )

    print(
        "Local state was NOT changed."
    )

    token = None

    raise SystemExit(
        31
    )


print(
    "MY TEAM FETCH: PASS"
)


try:

    snapshot = snapshot_from_my_team(
        payload,
        entry_id=entry_id,
        players_by_id=players,
    )


except FPLAccountError as exc:

    print(
        "MY TEAM PARSE: FAIL"
    )

    print(
        str(exc)
    )

    print(
        "Local state was NOT changed."
    )

    token = None

    raise SystemExit(
        32
    )


print(
    "MY TEAM PARSE: PASS"
)


# ============================================================
# PREVIEW
# ============================================================

print()
print("=" * 78)
print("FPL ACCOUNT SYNC PREVIEW")
print("=" * 78)


print(
    "entry id:",
    snapshot.entry_id,
)

print(
    "players:",
    len(
        snapshot.player_ids
    ),
)

print(
    "bank:",
    f"£{snapshot.bank_tenths / 10:.1f}m",
)

print(
    "free transfers:",
    snapshot.free_transfers,
)

print(
    "transfer limit:",
    snapshot.transfer_limit,
)

print(
    "transfers made:",
    snapshot.transfers_made,
)


print()
print(
    f"{'PLAYER':<24}"
    f"{'NOW':>7}"
    f"{'BUY':>7}"
    f"{'SELL':>7}"
)

print(
    "-" * 45
)


for player_id in (
    snapshot.player_ids
):

    player = players[
        player_id
    ]


    current = (
        player.current_price
    )

    purchase = (
        snapshot
        .purchase_prices_tenths[
            player_id
        ]
    )

    selling = (
        snapshot
        .selling_prices_tenths[
            player_id
        ]
    )


    current_text = (
        "-"
        if current is None
        else f"{current / 10:.1f}"
    )


    print(
        f"{player.display_name:<24}"
        f"{current_text:>7}"
        f"{purchase / 10:>7.1f}"
        f"{selling / 10:>7.1f}"
    )


print()
print(
    "selling-price coverage:",
    f"{len(snapshot.selling_prices_tenths)}/15",
)

print(
    "purchase-price coverage:",
    f"{len(snapshot.purchase_prices_tenths)}/15",
)


# ============================================================
# APPLY TO LOCAL DESKTOP STATE
# ============================================================

new_state = apply_account_snapshot(
    old_state,
    snapshot,
)


try:

    validate_state(
        new_state,
        players,
    )

except DesktopStateError as exc:

    print()
    print(
        "LOCAL STATE VALIDATION: FAIL"
    )

    print(
        str(exc)
    )

    print(
        "Local state was NOT changed."
    )

    token = None

    raise SystemExit(
        41
    )


completeness_issues = account_state_issues(
    new_state,
    players,
)


if completeness_issues:

    print(
        "ACCOUNT COMPLETENESS GATE: FAIL"
    )

    for issue in completeness_issues:

        print(
            "-",
            issue,
        )

    token = None

    raise SystemExit(
        42
    )


print()
print(
    "LOCAL STATE VALIDATION: PASS"
)

print(
    "ACCOUNT COMPLETENESS GATE: PASS"
)


save_state(
    STATE_PATH,
    new_state,
)


# ============================================================
# VERIFY WRITE
# ============================================================

restored = load_state(
    STATE_PATH
)


write_gate = (
    restored.fpl_entry_id
    == entry_id

    and len(
        restored.player_ids
    )
    == 15

    and len(
        restored
        .selling_prices_tenths
    )
    == 15

    and len(
        restored
        .purchase_prices_tenths
    )
    == 15

    and restored.bank_tenths
    == snapshot.bank_tenths
)


if not write_gate:

    print()
    print(
        "STATE WRITE VERIFY: FAIL"
    )

    print(
        "Restoring previous local state."
    )

    copy2(
        BACKUP_PATH,
        STATE_PATH,
    )

    token = None

    raise SystemExit(
        43
    )


print(
    "STATE WRITE VERIFY: PASS"
)


# Explicitly remove our reference to the secret.
token = None

captured[
    "token"
] = None


print()
print("=" * 78)
print("DESKTOP-003B3B RESULT")
print("=" * 78)

print(
    "Edge connection          : PASS"
)

print(
    "browser authentication   : PASS"
)

print(
    "entry id                 :",
    restored.fpl_entry_id,
)

print(
    "my-team                  : PASS"
)

print(
    "squad                    :",
    f"{len(restored.player_ids)}/15",
)

print(
    "selling prices           :",
    f"{len(restored.selling_prices_tenths)}/15",
)

print(
    "purchase prices          :",
    f"{len(restored.purchase_prices_tenths)}/15",
)

print(
    "bank                     :",
    f"£{restored.bank_tenths / 10:.1f}m",
)

print(
    "free transfers           :",
    restored.free_transfers,
)

print(
    "local state saved        : PASS"
)

print(
    "FPL account modified     : NO"
)

print(
    "token printed            : NO"
)

print(
    "token saved              : NO"
)

print()
print(
    "DESKTOP-003B3B GATE: PASS"
)
