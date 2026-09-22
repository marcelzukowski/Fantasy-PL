from pathlib import Path

source = Path(
    "scripts/aggregate_minutes_v21_exact_ab.py"
)

target = Path(
    "scripts/aggregate_minutes_v21_fair_ab.py"
)

text = source.read_text(
    encoding="utf-8"
)

text = text.replace(
    "minutes_v21_replay_report_seed",
    "minutes_v21_fair_report_seed",
)

text = text.replace(
    "MINUTES V1 vs V2.1 | EXACT PRE-DEADLINE GW4",
    "MINUTES V1 vs V2.1 | FAIR CALIBRATED PRE-DEADLINE GW4",
)

text = text.replace(
    "minutes_v21_exact_gw4_ab.txt",
    "minutes_v21_fair_gw4_ab.txt",
)

target.write_text(
    text,
    encoding="utf-8",
)

print(
    "fair aggregator prepared"
)
