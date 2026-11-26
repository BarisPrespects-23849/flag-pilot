"""`flagpilot recommend <id>`, `ship <id>`, `cleanup <id>` and `retire <flag>`."""

import argparse
import json
import sys
from pathlib import Path

from flagpilot import card, cleanup, recommend, repo, retire, settings, ship
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

    cln = commands.add_parser("cleanup", help="open a pull request that removes the flag")
    cln.add_argument("experiment_id", type=int)
    cln.add_argument("--apply", action="store_true", help="branch, edit, test, push, open the PR")
    cln.add_argument("--assume-winner", metavar="KEY",
                     help="preview only: pretend this variant (or 'control') won")
    cln.add_argument("--patch", type=Path, help="apply this diff instead of the automatic edit")

    ret = commands.add_parser("retire", help="archive the flag after cleanup")
    ret.add_argument("flag")
    ret.add_argument("--apply", action="store_true", help="really archive")
    ret.add_argument("--confirm", help="the flag name, exactly as a person typed it")
    ret.add_argument("--no-code", action="store_true",
                     help="the flag never had code: skip the pull request check")

    args = parser.parse_args(argv)
    try:
        thresholds = settings.load()
        if args.command == "ship":
            return ship.ship(args.experiment_id, thresholds, apply=args.apply,
                             confirm=args.confirm, expect_winner=args.expect_winner)
        if args.command == "cleanup":
            return cleanup.cleanup(args.experiment_id, thresholds, apply=args.apply,
                                   assume_winner=args.assume_winner, patch=args.patch)
        if args.command == "retire":
            return retire.retire(args.flag, thresholds, apply=args.apply,
                                 no_code=args.no_code, confirm=args.confirm)
        if args.refresh:
            recommend.refresh(args.experiment_id)
        decision = recommend.recommend(args.experiment_id, thresholds)
        if args.json:
            print(json.dumps(decision, separators=(",", ":")))
        else:
            print(card.render(decision))
    except (cli.CliError, repo.RepoError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
