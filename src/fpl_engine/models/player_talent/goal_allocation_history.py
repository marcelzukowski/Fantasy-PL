"""Canonical prior-season goal-allocation proxy materialization.

This module materializes the validated goal-allocation promotion candidate.

Important semantics:
- source feature is historical TOTAL xG, potentially including penalties,
- it is NOT npxG,
- it must never replace talent_npxg_per90,
- it is intended only as a relative player weight when dividing the
  non-penalty team goal envelope,
- only players with canonical prior-season evidence are eligible for
  challenger allocation; unmatched players retain Event V1 behaviour.

The validated configuration is:
- shrinkage prior minutes: 600,
- alpha: 0.55,
- identity: official FPL identity key -> canonical player_id.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping
import json
import lzma
import math

import pandas as pd

from fpl_engine.current_history import (
    _id,
    _receipts,
)

from fpl_engine.data.identity import (
    IdentityResolutionError,
    official_fpl_player_identity_key,
)

from fpl_engine.data.raw_store import RawStore

from .goal_allocation import (
    GoalAllocationProxyConfig,
    predict_goal_allocation_proxy,
)


@dataclass(frozen=True)
class GoalAllocationPlayerRef:
    player_id: str
    position: str
    display_name: str | None = None


@dataclass(frozen=True)
class GoalAllocationHistoryRow:
    player_id: str
    display_name: str | None
    position: str

    source_season: str | None
    source_provider_player_ids: tuple[int, ...]

    source_total_xg: float | None
    source_minutes: float

    position_prior_per90: float
    frozen_total_xg_rate_per90: float
    goal_allocation_proxy_per90: float

    alpha: float
    used_historical_total_xg: bool

    identity_method: str
    source_metric: str
    intended_use: str

    model_version: str
    feature_version: str


@dataclass(frozen=True)
class GoalAllocationProxyArtifact:
    artifact_version: str

    source_season: str
    prediction_timestamp: datetime

    alpha: float
    prior_minutes: float

    source_repository_ref: str
    source_checksum: str

    current_player_count: int
    strict_identity_player_count: int
    historical_player_count: int

    matched_count: int
    position_mismatch_count: int
    no_history_count: int
    unresolved_vaastav_rows: int

    rows: tuple[
        GoalAllocationHistoryRow,
        ...
    ]

    @property
    def match_rate(
        self,
    ) -> float:

        if self.current_player_count == 0:
            return 0.0

        return (
            self.matched_count
            / self.current_player_count
        )


    def evidence_proxy_by_player(
        self,
    ) -> Mapping[str, float]:

        return MappingProxyType({
            row.player_id:
                row.goal_allocation_proxy_per90
            for row in self.rows
            if row.used_historical_total_xg
        })


    def to_dict(
        self,
    ) -> dict:

        payload = asdict(
            self
        )

        payload[
            "prediction_timestamp"
        ] = (
            self.prediction_timestamp
            .isoformat()
        )

        payload[
            "match_rate"
        ] = self.match_rate

        payload[
            "production_projection_modified"
        ] = False

        payload[
            "status"
        ] = (
            "PROMOTION_CANDIDATE"
        )

        return payload


def _utc(
    value: datetime,
) -> datetime:

    if (
        not isinstance(
            value,
            datetime,
        )
        or value.tzinfo is None
        or value.utcoffset() is None
    ):

        raise ValueError(
            "prediction_timestamp "
            "must be timezone-aware"
        )

    return value.astimezone(
        timezone.utc
    )


def _position(
    value,
) -> str:

    value = str(
        value or ""
    ).upper()

    return {
        "GKP": "GK",
        "GOALKEEPER": "GK",
        "DEFENDER": "DEF",
        "MIDFIELDER": "MID",
        "FORWARD": "FWD",
    }.get(
        value,
        value,
    )


def _resolve_receipt(
    receipt_index,
    *,
    source_record_id: str,
    checksum: str,
):

    target = str(
        source_record_id
    )

    expected = str(
        checksum
    )


    direct = receipt_index.get(
        target
    )

    if (
        direct is not None
        and str(
            getattr(
                direct,
                "checksum",
                "",
            )
        )
        == expected
    ):

        return direct


    matches = []


    for key, receipt in (
        receipt_index.items()
    ):

        key_text = str(
            key
        )

        record_text = str(
            getattr(
                receipt,
                "source_record_id",
                "",
            )
            or ""
        )

        actual_checksum = str(
            getattr(
                receipt,
                "checksum",
                "",
            )
        )


        identifier_match = any((
            key_text == target,
            key_text.endswith(
                f":{target}"
            ),
            record_text == target,
            record_text.endswith(
                f":{target}"
            ),
        ))


        if (
            identifier_match
            and actual_checksum
            == expected
        ):

            matches.append(
                receipt
            )


    if not matches:

        raise RuntimeError(
            "Missing RawStore receipt: "
            f"{source_record_id}"
        )


    unique = {}


    for receipt in matches:

        identity = str(
            getattr(
                receipt,
                "snapshot_id",
                None,
            )
            or getattr(
                receipt,
                "payload_path",
                None,
            )
            or repr(
                receipt
            )
        )

        unique[
            identity
        ] = receipt


    if len(
        unique
    ) != 1:

        raise RuntimeError(
            "Ambiguous RawStore receipt: "
            f"{source_record_id}; "
            f"candidates={len(unique)}"
        )


    return next(
        iter(
            unique.values()
        )
    )


def build_strict_goal_allocation_proxy(
    *,
    project_root: Path,
    source_season: str,
    prediction_timestamp: datetime,
    current_players: Iterable[
        GoalAllocationPlayerRef
    ],
    config: GoalAllocationProxyConfig = (
        GoalAllocationProxyConfig()
    ),
) -> GoalAllocationProxyArtifact:

    root = Path(
        project_root
    ).resolve()

    at = _utc(
        prediction_timestamp
    )

    players = tuple(
        current_players
    )


    if len({
        row.player_id
        for row in players
    }) != len(
        players
    ):

        raise ValueError(
            "current_players contains "
            "duplicate canonical player IDs"
        )


    strict_root = (
        root
        / "data"
        / "interim"
        / "strict"
        / source_season
    )

    manifest_path = (
        strict_root
        / "source_manifest.json"
    )


    if not manifest_path.exists():

        raise RuntimeError(
            "STRICT source manifest "
            f"missing for {source_season}"
        )


    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )


    prediction_points = (
        manifest.get(
            "prediction_points"
        )
    )


    if not isinstance(
        prediction_points,
        list,
    ) or not prediction_points:

        raise RuntimeError(
            "STRICT manifest has no "
            "prediction_points"
        )


    #
    # Full prior-season history is legal only
    # when every materialized point predates T.
    #
    for point in prediction_points:

        timestamp = (
            point.get(
                "snapshot_timestamp"
            )
            or point.get(
                "prediction_timestamp"
            )
        )

        if timestamp is None:
            continue

        known = datetime.fromisoformat(
            str(
                timestamp
            ).replace(
                "Z",
                "+00:00",
            )
        )

        if known.tzinfo is None:

            raise RuntimeError(
                "STRICT snapshot timestamp "
                "is not timezone-aware"
            )

        if (
            known.astimezone(
                timezone.utc
            )
            >= at
        ):

            raise RuntimeError(
                "Goal-allocation prior-season "
                "source is not known before "
                "prediction_timestamp"
            )


    raw = RawStore(
        root
        / "data"
        / "raw"
    )

    receipt_index = _receipts(
        raw.root
    )


    #
    # --------------------------------------------------------
    # Reconstruct exactly the same canonical player identity
    # mapping as current_history.load_strict_historical_context.
    # --------------------------------------------------------
    #

    first_elements = {}


    for point in sorted(
        prediction_points,
        key=lambda row:
            int(
                row.get(
                    "gameweek",
                    0,
                )
            ),
    ):

        snapshot_path = point.get(
            "snapshot_path"
        )

        checksum = point.get(
            "checksum"
        )


        if (
            not snapshot_path
            or not checksum
        ):

            raise RuntimeError(
                "STRICT prediction point "
                "lacks snapshot_path/checksum"
            )


        receipt = _resolve_receipt(
            receipt_index,
            source_record_id=str(
                snapshot_path
            ),
            checksum=str(
                checksum
            ),
        )


        payload = json.loads(
            lzma.decompress(
                raw.read_bytes(
                    receipt
                )
            )
        )


        for element in payload.get(
            "elements",
            [],
        ):

            provider_id = int(
                element[
                    "id"
                ]
            )

            first_elements.setdefault(
                provider_id,
                element,
            )


    provider_to_player = {}
    canonical_to_provider = {}
    seen_identity_keys = {}


    for provider_id, element in (
        first_elements.items()
    ):

        try:

            identity_key = (
                official_fpl_player_identity_key(
                    element
                )
            )

        except IdentityResolutionError as exc:

            raise RuntimeError(
                f"STRICT {source_season} "
                f"player {provider_id} lacks "
                f"a safe identity key: {exc}"
            ) from exc


        previous = (
            seen_identity_keys.get(
                identity_key
            )
        )


        if (
            previous is not None
            and previous
            != provider_id
        ):

            raise RuntimeError(
                "STRICT player identity "
                "collision: "
                f"{previous} and "
                f"{provider_id}"
            )


        seen_identity_keys[
            identity_key
        ] = provider_id


        player_id = _id(
            "ply",
            identity_key,
        )


        previous_provider = (
            canonical_to_provider.get(
                player_id
            )
        )


        if (
            previous_provider
            is not None
            and previous_provider
            != provider_id
        ):

            raise RuntimeError(
                "Canonical player ID collision"
            )


        provider_to_player[
            provider_id
        ] = player_id

        canonical_to_provider[
            player_id
        ] = provider_id


    #
    # --------------------------------------------------------
    # Load the immutable STRICT Vaastav merged_gw frame.
    # --------------------------------------------------------
    #

    repository_ref = str(
        manifest[
            "vaastav_repository_ref"
        ]
    )

    vaastav = manifest.get(
        "vaastav"
    )


    if not isinstance(
        vaastav,
        dict,
    ):

        raise RuntimeError(
            "STRICT Vaastav manifest "
            "entry missing"
        )


    source_checksum = str(
        vaastav[
            "checksum"
        ]
    )

    source_record_id = (
        f"{repository_ref}:"
        f"{source_season}:"
        f"merged_gw"
    )


    receipt = _resolve_receipt(
        receipt_index,
        source_record_id=(
            source_record_id
        ),
        checksum=(
            source_checksum
        ),
    )


    frame = pd.read_csv(
        BytesIO(
            raw.read_bytes(
                receipt
            )
        )
    )


    required = {
        "element",
        "minutes",
        "expected_goals",
        "position",
    }


    missing = (
        required
        - set(
            frame.columns
        )
    )


    if missing:

        raise RuntimeError(
            "STRICT Vaastav frame "
            "missing columns: "
            + ", ".join(
                sorted(
                    missing
                )
            )
        )


    frame = frame.copy()

    frame[
        "provider_player_id"
    ] = pd.to_numeric(
        frame[
            "element"
        ],
        errors="coerce",
    )

    frame[
        "minutes_numeric"
    ] = pd.to_numeric(
        frame[
            "minutes"
        ],
        errors="coerce",
    )

    frame[
        "expected_goals_numeric"
    ] = pd.to_numeric(
        frame[
            "expected_goals"
        ],
        errors="coerce",
    )

    frame[
        "position_canonical"
    ] = frame[
        "position"
    ].map(
        _position
    )


    frame = frame[
        frame[
            "provider_player_id"
        ].notna()
    ].copy()


    frame[
        "provider_player_id"
    ] = frame[
        "provider_player_id"
    ].astype(
        int
    )


    frame[
        "player_id"
    ] = frame[
        "provider_player_id"
    ].map(
        provider_to_player
    )


    unresolved_vaastav_rows = int(
        frame[
            "player_id"
        ].isna().sum()
    )


    frame = frame[
        frame[
            "player_id"
        ].notna()
    ].copy()


    #
    # --------------------------------------------------------
    # Aggregate prior-season total-xG evidence.
    # --------------------------------------------------------
    #

    historical = {}


    for player_id, group in (
        frame.groupby(
            "player_id",
            sort=False,
        )
    ):

        valid = group[
            group[
                "minutes_numeric"
            ].notna()
            & group[
                "expected_goals_numeric"
            ].notna()
            & (
                group[
                    "minutes_numeric"
                ]
                > 0.0
            )
        ]


        if valid.empty:
            continue


        position_minutes = (
            valid.groupby(
                "position_canonical"
            )[
                "minutes_numeric"
            ]
            .sum()
            .sort_values(
                ascending=False
            )
        )


        if position_minutes.empty:
            continue


        historical_position = str(
            position_minutes.index[
                0
            ]
        )


        historical[
            str(
                player_id
            )
        ] = {
            "position": (
                historical_position
            ),
            "total_xg": float(
                valid[
                    "expected_goals_numeric"
                ].sum()
            ),
            "minutes": float(
                valid[
                    "minutes_numeric"
                ].sum()
            ),
            "provider_ids": tuple(
                sorted({
                    int(
                        value
                    )
                    for value in valid[
                        "provider_player_id"
                    ]
                })
            ),
        }


    #
    # --------------------------------------------------------
    # Materialize one row for every current player.
    # --------------------------------------------------------
    #

    output = []

    matched = 0
    position_mismatch = 0
    no_history = 0


    for player in players:

        position = _position(
            player.position
        )

        evidence = historical.get(
            player.player_id
        )


        use_evidence = False
        source_xg = None
        source_minutes = 0.0
        provider_ids = ()


        if evidence is None:

            no_history += 1


        elif (
            evidence[
                "position"
            ]
            != position
        ):

            position_mismatch += 1


        else:

            use_evidence = True

            source_xg = float(
                evidence[
                    "total_xg"
                ]
            )

            source_minutes = float(
                evidence[
                    "minutes"
                ]
            )

            provider_ids = tuple(
                evidence[
                    "provider_ids"
                ]
            )

            matched += 1


        prediction = (
            predict_goal_allocation_proxy(
                player_id=(
                    player.player_id
                ),
                position=position,
                source_season=(
                    source_season
                    if use_evidence
                    else None
                ),
                source_total_xg=(
                    source_xg
                ),
                source_minutes=(
                    source_minutes
                ),
                config=config,
            )
        )


        output.append(
            GoalAllocationHistoryRow(
                player_id=(
                    player.player_id
                ),
                display_name=(
                    player.display_name
                ),
                position=position,
                source_season=(
                    prediction.source_season
                ),
                source_provider_player_ids=(
                    provider_ids
                ),
                source_total_xg=(
                    prediction
                    .source_total_xg
                ),
                source_minutes=(
                    prediction
                    .source_minutes
                ),
                position_prior_per90=(
                    prediction
                    .position_prior_per90
                ),
                frozen_total_xg_rate_per90=(
                    prediction
                    .frozen_total_xg_rate_per90
                ),
                goal_allocation_proxy_per90=(
                    prediction
                    .goal_allocation_proxy_per90
                ),
                alpha=(
                    prediction.alpha
                ),
                used_historical_total_xg=(
                    prediction
                    .used_historical_total_xg
                ),
                identity_method=(
                    "official_fpl_player_identity_key"
                    "_to_canonical_player_id"
                ),
                source_metric=(
                    prediction
                    .source_metric
                ),
                intended_use=(
                    prediction
                    .intended_use
                ),
                model_version=(
                    prediction
                    .model_version
                ),
                feature_version=(
                    prediction
                    .feature_version
                ),
            )
        )


    output.sort(
        key=lambda row:
            row.player_id
    )


    if (
        matched
        + position_mismatch
        + no_history
        != len(
            players
        )
    ):

        raise RuntimeError(
            "Goal-allocation coverage "
            "accounting invariant failed"
        )


    return GoalAllocationProxyArtifact(
        artifact_version=(
            "goal_allocation_proxy_"
            "canonical_v1"
        ),
        source_season=(
            source_season
        ),
        prediction_timestamp=(
            at
        ),
        alpha=(
            config.alpha
        ),
        prior_minutes=(
            config.prior_minutes
        ),
        source_repository_ref=(
            repository_ref
        ),
        source_checksum=(
            source_checksum
        ),
        current_player_count=(
            len(
                players
            )
        ),
        strict_identity_player_count=(
            len(
                provider_to_player
            )
        ),
        historical_player_count=(
            len(
                historical
            )
        ),
        matched_count=(
            matched
        ),
        position_mismatch_count=(
            position_mismatch
        ),
        no_history_count=(
            no_history
        ),
        unresolved_vaastav_rows=(
            unresolved_vaastav_rows
        ),
        rows=tuple(
            output
        ),
    )
