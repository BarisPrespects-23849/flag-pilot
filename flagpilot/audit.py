"""Append-only audit log for every state-changing plan and call (NOTES.md §5)."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from flagpilot.config import ROOT

AUDIT_PATH = ROOT / "audit.jsonl"


def body_hash(body: object) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def record(
    *,
    action: str,
    tier: int,
    method: str,
    path: str,
    body: object,
    dry_run: bool,
    status: str,
    approved_by: str | None = None,
    response_id: int | str | None = None,
    log_path: Path | None = None,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": "flagpilot",
        "action": action,
        "tier": tier,
        "method": method,
        "path": path,
        "body_hash": body_hash(body),
        "dry_run": dry_run,
        "approved_by": approved_by,
        "status": status,
        "response_id": response_id,
    }
    with (log_path or AUDIT_PATH).open("a") as log:
        log.write(json.dumps(entry) + "\n")
