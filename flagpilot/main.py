"""`flagpilot recommend <id>` and `flagpilot ship <id>`."""

import argparse
import json
import sys

from flagpilot import card, recommend, settings, ship
from flagpilot import flagsmith_cli as cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flagpilot", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    rec = commands.add_parser("recommend", help="verdict from the experiment's results")
    rec.add_argument("experiment_id", type=int)
    rec.add_argument("--json", action="store_true", help="print the decision object")
    rec.add_argument("--refresh", action="store_true",
                     help="recompute first (results at most once per 5 minutes)")

    shp = commands.add_parser("ship", help="end the experiment and ship the winner")
    shp.add_argument("experiment_id", type=int)
    shp.add_argument("--apply", action="store_true", help="really ship (irreversible)")
    shp.add_argument("--confirm", help="the experiment name, exactly as a person typed it")
    shp.add_argument("--expect-winner", help="winner shown in the approved dry-run")

    args = parser.parse_args(argv)
    try:
        thresholds = settings.load()
        if args.command == "ship":
            return ship.ship(args.experiment_id, thresholds, apply=args.apply,
                             confirm=args.confirm, expect_winner=args.expect_winner)
        if args.refresh:
            recommend.refresh(args.experiment_id)
        decision = recommend.recommend(args.experiment_id, thresholds)
        if args.json:
            print(json.dumps(decision, separators=(",", ":")))
        else:
            print(card.render(decision))
    except cli.CliError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
