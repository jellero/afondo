"""Run operator-authorized metadata discovery once. Suitable for an external scheduler.

Example: python -m afondo.sync_sources --dry-run
         python -m afondo.sync_sources --once
No unapproved sources are fetched. This command must run only in a trusted
operator environment with controlled network egress.
"""
from __future__ import annotations

import argparse
import json
import sys

from afondo.db import initialize
from afondo.source_ingestion import SourceSyncError, sync_source
from afondo.source_registry import SourceConfigError, configured_sources


def run(source_ids: set[str] | None = None, dry_run: bool = True) -> int:
    initialize()
    errors = 0
    sources = configured_sources()
    unknown = (source_ids or set()) - {s["id"] for s in sources}
    if unknown:
        print(json.dumps({"error": "Unknown source IDs", "ids": sorted(unknown)}))
        return 2
    for source in sources:
        if source_ids is not None and source["id"] not in source_ids:
            continue
        if not source["enabled"]:
            print(json.dumps({"source_id": source["id"], "status": "skipped",
                              "reason": source["permission_status"]}))
            continue
        if dry_run:
            print(json.dumps({"source_id": source["id"], "status": "ready",
                              "adapter": source["adapter"]}))
            continue
        try:
            print(json.dumps(sync_source(source)))
        except (SourceSyncError, SourceConfigError, ValueError) as exc:
            errors += 1
            print(json.dumps({"source_id": source["id"], "status": "failed",
                              "error": str(exc)}), file=sys.stderr)
    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="AFONDO operator-only RSS/API metadata discovery")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Display readiness without fetching")
    mode.add_argument("--once", action="store_true", help="Run one eligible metadata sync")
    parser.add_argument("--source", action="append", default=None, help="Source ID (repeatable)")
    args = parser.parse_args()
    raise SystemExit(run(
        source_ids=set(args.source) if args.source else None,
        dry_run=not args.once,
    ))


if __name__ == "__main__":
    main()
