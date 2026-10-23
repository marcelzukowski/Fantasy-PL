# Oracle and property tests

Use small exact oracles to check planner behavior where exhaustive search is tractable. State the exact universe, horizon, transfer bound, constraints, objective and tie policy so a passing result has a clear scope. Include adversarial cases for club caps, funding cycles, hits, free-transfer rollover, delayed payoff, HOLD, and terminal FT value when relevant.

Useful properties include:

- every emitted squad is legal and has exactly the configured positions and club limits;
- costs use personal selling prices and bank, and hits/free transfers roll forward consistently;
- repeated runs with identical inputs are deterministic;
- reported totals replay from the serialized path and match the declared objective;
- HOLD comparison uses the complete objective and chooses HOLD within absolute `1e-9`;
- schema round-trips preserve IDs, plan identity, preview/lineup and captaincy data.

A bounded oracle passing does not establish global optimality outside its exact model and search scope. Keep known counterexamples visible: K<=2 pruning counterexamples and the K<=5 expanded-universe `8.271` objective gap. Report the oracle scope and unresolved cases; never hide a miss behind an incumbent-preservation fallback.

For a documentation-only task, do not run tests. For code changes, run the smallest relevant focused checks requested by the task; broad suites or expensive data work require explicit scope.
