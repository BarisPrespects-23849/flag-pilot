"""Push a branch to origin, and log success only once origin is confirmed to have it.

Dry-run is the default.

    python -m flagpilot.push [--branch main] [--apply --approved-by NAME]
"""

import argparse
import sys
from pathlib import Path

from flagpilot import audit, config, repo

TIER = 2


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", default="main")
    parser.add_argument("--apply", action="store_true", help="really push")
    parser.add_argument("--approved-by", help="who approved this push (required with --apply)")
    args = parser.parse_args(argv)
    if args.apply and not args.approved_by:
        parser.error("--apply requires --approved-by")
    root = root or config.ROOT

    def log(status: str, head: str | None) -> None:
        audit.record(action="git_push", tier=TIER, method="CLI",
                     path=f"git: origin/{args.branch}", body={"branch": args.branch, "head": head},
                     dry_run=not args.apply, status=status,
                     approved_by=args.approved_by if args.apply else None)

    head = None
    try:
        head = repo.git(root, "rev-parse", "HEAD").strip()
        if not args.apply:
            ahead = repo.git(root, "log", "--format=  %h %s", f"origin/{args.branch}..HEAD")
            print(f"DRY-RUN  tier {TIER}  git push origin {args.branch}  (HEAD {head[:7]})")
            print(ahead.rstrip() or "  no commits ahead of the last known origin")
            log("planned", head)
            return 0
        head = repo.push(root, args.branch)
    except repo.RepoError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        log(f"failed: {error}", head)
        return 1
    log("success", head)
    print(f"Pushed and verified: origin/{args.branch} is at {head[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
