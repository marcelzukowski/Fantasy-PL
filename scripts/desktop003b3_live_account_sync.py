from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from shutil import copy2

import httpx


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(
    PROJECT_ROOT
) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


from desktop_app.data_access import (
    load_players,
    resolve_player_source,
)

from desktop_app.fpl_account import (
    FPLAccountError,
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


ROOT = Path.cwd()

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
    / "desktop003b3_live_sync"
    / "squad_state_before_live_sync.json"
)

FPL_HOME = (
    "https://fantasy.premierleague.com/"
)

FPL_MY_TEAM_PAGE = (
    "https://fantasy.premierleague.com/my-team"
)

FPL_API_ROOT = (
    "https://fantasy.premierleague.com/api"
)


print()
print("=" * 78)
print("DESKTOP-003B3 LIVE FPL ACCOUNT SYNC")
print("=" * 78)

print()
print("FPL access mode: READ ONLY")
print("Transfers: NO")
print("Captain changes: NO")
print("Chip changes: NO")
print("Password captured by application: NO")
print("Bearer token printed: NO")
print("Bearer token written to project: NO")


# ============================================================
# CURRENT LOCAL STATE
# ============================================================

if not STATE_PATH.exists():

    raise SystemExit(
        "Local squad_state.json does not exist."
    )


try:

    old_state = load_state(
        STATE_PATH
    )

except DesktopStateError as exc:

    raise SystemExit(
        f"Could not load local state: {exc}"
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
    old_state.bank_tenths / 10,
)

print(
    "free transfers:",
    old_state.free_transfers,
)

print(
    "existing FPL entry id:",
    old_state.fpl_entry_id,
)

print(
    "existing selling prices:",
    len(
        old_state.selling_prices_tenths
    ),
)

print(
    "backup:",
    BACKUP_PATH.relative_to(
        ROOT
    ),
)


# ============================================================
# CURRENT PLAYER POOL
# ============================================================

player_source = resolve_player_source(
    ROOT
)

players = load_players(
    player_source
)


provider_count = sum(
    player.provider_id is not None
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
    "players:",
    len(
        players
    ),
)

print(
    "provider ids:",
    f"{provider_count}/{len(players)}",
)


if provider_count != len(
    players
):

    raise SystemExit(
        "Provider ID coverage is incomplete."
    )


# ============================================================
# BROWSER AUTH
# ============================================================

print()
print("=== BROWSER LOGIN ===")


try:

    from playwright.sync_api import (
        Error as PlaywrightError,
        sync_playwright,
    )

except Exception as exc:

    raise SystemExit(
        "Playwright import failed: "
        + str(
            exc
        )
    )


local_app_data = os.environ.get(
    "LOCALAPPDATA"
)


if not local_app_data:

    raise SystemExit(
        "LOCALAPPDATA is unavailable."
    )


profile_dir = (
    Path(
        local_app_data
    )
    / "FPLControlCenter"
    / "browser_profile"
)


profile_dir.mkdir(
    parents=True,
    exist_ok=True,
)


captured = {
    "token":
        None,

    "entry_id":
        None,
}


MY_TEAM_PATTERN = re.compile(
    r"/api/my-team/(\d+)/?"
)


def on_request(
    request,
):

    try:

        headers = request.headers

    except Exception:

        return


    auth = headers.get(
        "x-api-authorization"
    )


    if (
        auth
        and auth.casefold().startswith(
            "bearer "
        )
        and captured[
            "token"
        ]
        is None
    ):

        token = auth[
            7:
        ].strip()


        if token:

            captured[
                "token"
            ] = token


            print()
            print(
                "AUTH TOKEN CAPTURE: PASS"
            )

            print(
                "Token value: [HIDDEN]"
            )


    match = MY_TEAM_PATTERN.search(
        request.url
    )


    if match:

        captured[
            "entry_id"
        ] = int(
            match.group(
                1
            )
        )


browser_channel = None


with sync_playwright() as p:

    context = None


    for candidate in (
        "msedge",
        "chrome",
    ):

        try:

            context = (
                p.chromium
                .launch_persistent_context(
                    user_data_dir=str(
                        profile_dir
                    ),

                    channel=candidate,

                    headless=False,

                    viewport=None,
                )
            )

            browser_channel = (
                candidate
            )

            break


        except PlaywrightError:

            context = None


    if context is None:

        print()
        print(
            "Could not start Microsoft Edge "
            "or Google Chrome through Playwright."
        )

        print(
            "No account data was changed."
        )

        raise SystemExit(
            31
        )


    print(
        "browser:",
        browser_channel,
    )

    print(
        "browser profile:",
        profile_dir,
    )


    context.on(
        "request",
        on_request,
    )


    if context.pages:

        page = context.pages[
            0
        ]

    else:

        page = context.new_page()


    try:

        page.goto(
            FPL_HOME,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    except Exception:

        pass


    # Privacy-preserving cookie option if the banner is present.
    try:

        page.locator(
            "#onetrust-reject-all-handler"
        ).click(
            timeout=4000
        )

    except Exception:

        pass


    # Try to open the official sign-in page.
    # If selectors change, the user can simply click Log in manually.
    login_clicked = False


    for role in (
        "button",
        "link",
    ):

        try:

            locator = page.get_by_role(
                role,
                name=re.compile(
                    r"log in|sign in",
                    re.IGNORECASE,
                ),
            )

            locator.first.click(
                timeout=4000
            )

            login_clicked = True

            break

        except Exception:

            pass


    print()
    print(
        "A browser window is now open."
    )

    print(
        "Log in ONLY inside the official "
        "Premier League / FPL browser page."
    )

    print(
        "Do NOT type your password into "
        "PowerShell."
    )

    print(
        "After login, leave the browser open."
    )

    print()
    print(
        "Waiting for authenticated FPL traffic..."
    )


    deadline = (
        time.monotonic()
        + 240
    )

    nudged = False


    while (
        captured[
            "token"
        ]
        is None
        and time.monotonic()
        < deadline
    ):

        page.wait_for_timeout(
            500
        )


        remaining = (
            deadline
            - time.monotonic()
        )


        # Once login has had time to finish,
        # navigate to My Team to force an
        # authenticated API request.
        if (
            not nudged
            and remaining
            < 195
        ):

            try:

                page.goto(
                    FPL_MY_TEAM_PAGE,
                    wait_until=(
                        "domcontentloaded"
                    ),
                    timeout=60000,
                )

            except Exception:

                pass


            nudged = True


    if captured[
        "token"
    ] is None:

        print()
        print(
            "AUTH TOKEN CAPTURE: FAIL"
        )

        print(
            "No token was detected within "
            "240 seconds."
        )

        print(
            "Local squad state was NOT changed."
        )


        context.close()

        raise SystemExit(
            32
        )


    # Make sure My Team is visited after token capture
    # so we also have a chance to infer the Entry ID
    # directly from network traffic.
    if captured[
        "entry_id"
    ] is None:

        try:

            page.goto(
                FPL_MY_TEAM_PAGE,
                wait_until="domcontentloaded",
                timeout=60000,
            )

        except Exception:

            pass


        for _ in range(
            20
        ):

            if captured[
                "entry_id"
            ] is not None:

                break


            page.wait_for_timeout(
                500
            )


    context.close()


token = captured[
    "token"
]


# ============================================================
# GET /api/me/
# ============================================================

print()
print("=== FPL PROFILE ===")


headers = {
    "Accept":
        "application/json",

    "X-API-Authorization":
        f"Bearer {token}",

    "User-Agent":
        "FPLControlCenter/desktop",
}


try:

    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
    ) as client:

        me_response = client.get(
            FPL_API_ROOT
            + "/me/",
            headers=headers,
        )


        print(
            "/api/me status:",
            me_response.status_code,
        )


        me_response.raise_for_status()

        me_payload = (
            me_response.json()
        )


except Exception as exc:

    print(
        "PROFILE FETCH: FAIL"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    print(
        "Local squad state was NOT changed."
    )

    raise SystemExit(
        41
    )


entry_id = captured[
    "entry_id"
]


if not entry_id:

    if isinstance(
        me_payload,
        dict,
    ):

        raw_entry = me_payload.get(
            "entry"
        )


        if isinstance(
            raw_entry,
            dict,
        ):

            raw_entry = raw_entry.get(
                "id"
            )


        try:

            if raw_entry is not None:

                entry_id = int(
                    raw_entry
                )

        except (
            TypeError,
            ValueError,
        ):

            entry_id = None


if not entry_id:

    print(
        "ENTRY ID RESOLUTION: FAIL"
    )

    print(
        "Local squad state was NOT changed."
    )

    raise SystemExit(
        42
    )


print(
    "ENTRY ID RESOLUTION: PASS"
)

print(
    "entry id:",
    entry_id,
)


# ============================================================
# GET /api/my-team/<entry_id>/
# ============================================================

print()
print("=== MY TEAM ===")


try:

    my_team = fetch_my_team(
        entry_id=entry_id,
        bearer_token=token,
    )


except FPLAccountError as exc:

    print(
        "MY TEAM FETCH: FAIL"
    )

    print(
        str(
            exc
        )
    )

    print(
        "Local squad state was NOT changed."
    )

    raise SystemExit(
        51
    )


print(
    "MY TEAM FETCH: PASS"
)


try:

    snapshot = snapshot_from_my_team(
        my_team,
        entry_id=entry_id,
        players_by_id=players,
    )


except FPLAccountError as exc:

    print(
        "MY TEAM PARSE: FAIL"
    )

    print(
        str(
            exc
        )
    )

    print(
        "Local squad state was NOT changed."
    )

    raise SystemExit(
        52
    )


print(
    "MY TEAM PARSE: PASS"
)


# ============================================================
# PREVIEW
# ============================================================

print()
print("=" * 78)
print("ACCOUNT SYNC PREVIEW")
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
    "transfers made in period:",
    snapshot.transfers_made,
)


print()
print(
    f"{'PLAYER':<24} "
    f"{'NOW':>6} "
    f"{'BUY':>6} "
    f"{'SELL':>6}"
)

print(
    "-" * 46
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
        f"{player.display_name:<24} "
        f"{current_text:>6} "
        f"{purchase / 10:>6.1f} "
        f"{selling / 10:>6.1f}"
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


print()
print(
    "chips used:"
)


for key, value in (
    snapshot.chips_used.items()
):

    print(
        f"  {key:<24}",
        value,
    )


# ============================================================
# APPLY LOCALLY
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
        str(
            exc
        )
    )

    print(
        "Local squad state was NOT changed."
    )

    raise SystemExit(
        61
    )


price_gate = (
    len(
        new_state
        .selling_prices_tenths
    )
    == 15

    and len(
        new_state
        .purchase_prices_tenths
    )
    == 15

    and all(
        price > 0
        for price
        in new_state
        .selling_prices_tenths
        .values()
    )

    and all(
        price > 0
        for price
        in new_state
        .purchase_prices_tenths
        .values()
    )
)


if not price_gate:

    print()
    print(
        "PERSONAL PRICE GATE: FAIL"
    )

    print(
        "Local squad state was NOT changed."
    )

    raise SystemExit(
        62
    )


print()
print(
    "LOCAL STATE VALIDATION: PASS"
)

print(
    "PERSONAL PRICE GATE: PASS"
)


save_state(
    STATE_PATH,
    new_state,
)


# ============================================================
# VERIFY WRITTEN STATE
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


print()
print(
    "STATE WRITE VERIFY:",
    (
        "PASS"
        if write_gate
        else "FAIL"
    ),
)


if not write_gate:

    print(
        "Restoring pre-sync backup."
    )

    copy2(
        BACKUP_PATH,
        STATE_PATH,
    )

    raise SystemExit(
        63
    )


# Explicitly discard the token variable.
token = None


print()
print("=" * 78)
print("DESKTOP-003B3 LIVE SYNC RESULT")
print("=" * 78)

print(
    "browser auth             : PASS"
)

print(
    "FPL profile              : PASS"
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
    "transfers executed       : NO"
)

print(
    "token printed            : NO"
)

print(
    "token saved in project   : NO"
)

print()
print(
    "DESKTOP-003B3 GATE: PASS"
)
