# V3 multi-transfer diagnostics

The scripts in this directory and the matching `tests/test_v3*` tests are diagnostic/experimental research artifacts. They do not enable or constitute production integration. Production integration is **NO-GO**; further multi-transfer research is deferred.

The separately authorized CP-SAT Phase1 (`cpsat_packages.py`, `cpsat_worker.py`, `cpsat_gw8.py`)
generates legal final packages using a linear all-roster projection surrogate only. It does not
enable production expansion or model the full V3 objective. See [Phase1 evidence](../../docs/cpsat-phase1.md)
and `tests/test_cpsat_transfer_packages.py`. Phase2 is not implemented.

Production remains the stable V3 planner with at most **K<=2 transfers per action** and its corrected complete-objective HOLD reconciliation, including current terminal free-transfer (FT) value. V22 remains the production simulator. Decision and Chip behavior are unchanged. Market Shadow has `production influence=false`.

## Known limits

1. Actions are limited to at most two transfers in production.
2. For current FT greater than two, no proven optimum among all legal K=3, K=4, or K=5 actions has been established.
3. Production V3 and the K<=5 challengers use approximate beam search; candidate or path retention does not prove global optimality.
4. Challenger C failed the full K<=5 `seeded_adversarial_1` oracle: exact objective **290.372** versus **282.101**, a gap of **8.271**. The earlier restricted-K2 cases are separate: C gap **0.708** on `seeded_adversarial_1`, and B gap **1.943** on `seeded_adversarial_3`.
5. Realised out-of-sample decision superiority has not been established.

The final readiness decision and supporting oracle table are recorded in [`scratch/v3_portfolio_20261022/validation_report.md`](../../scratch/v3_portfolio_20261022/validation_report.md). Its frozen local contexts and synthetic oracle cases do not establish historical or out-of-sample performance. Keep these scripts and tests available for research, but do not use them to enable production multi-transfer behavior.
