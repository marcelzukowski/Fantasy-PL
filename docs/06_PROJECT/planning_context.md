# Planning Context

`PlanningContext` is the immutable identity of one read-only FPL planning run.
It links a 15-player account state to one verified canonical projection run.

The SHA-256 `context_id` is calculated from canonical JSON with sorted player,
price, chip, model-version, freshness, and artifact-hash fields. It fingerprints
season, GW, deadline when supplied, bank, free transfers, owned-player selling
prices, chip state, projection-run ID, prediction timestamp, simulator and rule
versions, manifest digest, and required artifact digests.

It intentionally excludes absolute paths, GUI/display state, report creation
time, and any machine-specific values. Moving identical files therefore does not
change a semantic context.

Decision, Chip, and Analysis reports created under this contract carry the same
`context_id`. Chip evaluation and saved-analysis loading fail closed if identities
differ. Old reports without a context remain discoverable as `LEGACY / UNVERIFIED`;
they are not combined with current state and require a new analysis.

Required projection artifacts are verified against the existing run manifest:
`prediction_context`, `shadow_bundle`, `current_players`, `fixture_horizon`, and
`minutes`. Missing or changed artifacts produce `Projection artifact integrity
check failed.`
