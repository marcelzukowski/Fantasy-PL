# Production safety and release

## Account and secrets

FPL account use is read-only: do not submit transfers, chips, captaincy, squad confirmation or any other mutation. Keep bearer tokens in process memory only. Never ask for, print, commit or write passwords, tokens or secrets. Preserve `fpl_entry_id`, personal purchase/selling prices, bank and free transfers through state edits and saves. `status="cost"` does not mean zero FT; use the verified `limit - made` semantics.

## Runtime and data safety

Use the external project `.venv` for lightweight GUI workers. Never run `uv sync` or install dependencies without an explicit task. Do not trigger costly projections, full analyses, Chip Screen, provider refreshes or release builds unless requested. Keep Market Shadow production influence false. Do not treat scratch runs as production.

Protect the frozen engine baseline during unrelated work. Preserve unrelated edits and account data. Before replacing release artifacts, verify the requested build and smoke gates, ensure no live app instance is using the destination, and compare copied artifact identity. A skipped gate must be reported as skipped; do not claim release completion.

## Verification and reporting

Choose checks proportionate to the requested change. GUI changes may need offscreen behavior and geometry checks; package changes need archive and launch checks when explicitly requested. Do not run the full suite or expensive production workflows by habit. Report changed files, executed and skipped checks, and known limitations. Do not claim optimizer optimality without its mathematical model, solver status and exact search scope.
