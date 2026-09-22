from pathlib import Path
import json

RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/"
    "20260912T100351Z"
)


def inspect_file(name):

    path = RUN / name

    payload = json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )

    print()
    print(f"=== {name} ===")
    print("top type:", type(payload).__name__)


    if isinstance(payload, dict):

        print(
            "top keys:",
            list(payload.keys())
        )

        for key, value in payload.items():

            if isinstance(value, list):

                print(
                    f"{key}: list[{len(value)}]"
                )

                if value:

                    sample = value[0]

                    if isinstance(sample, dict):

                        print(
                            " sample keys:",
                            list(sample.keys())
                        )

                        print(
                            " sample:",
                            sample
                        )

                break

            elif isinstance(value, dict):

                print(
                    f"{key}: dict keys=",
                    list(value.keys())[:20]
                )


    elif isinstance(payload, list):

        print(
            "length:",
            len(payload)
        )

        if payload:

            sample = payload[0]

            if isinstance(sample, dict):

                print(
                    "sample keys:",
                    list(sample.keys())
                )

            print(
                "sample:",
                sample
            )


inspect_file(
    "player_projections.json"
)

inspect_file(
    "event_projections.json"
)
