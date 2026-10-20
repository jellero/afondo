"""Optional local background pre-analysis worker.

Explicit opt-in using Docker Compose 'automation' profile AND environment flag.
Article-level rights grants and existing daily quotas still apply.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from afondo.db import initialize
from afondo.preanalysis import process_once

MIN_INTERVAL_SECONDS = 900


def main() -> None:
    if os.getenv("AFONDO_ENABLE_PREANALYSIS") != "1":
        raise SystemExit(
            "Preanalysis worker disabled; set AFONDO_ENABLE_PREANALYSIS=1 explicitly"
        )
    period = os.getenv("AFONDO_PREANALYSIS_INTERVAL_SECONDS", "900")
    try:
        interval = int(period)
    except ValueError as exc:
        raise SystemExit("Invalid worker interval") from exc
    if interval < MIN_INTERVAL_SECONDS:
        raise SystemExit("Worker interval must be at least 900 seconds")
    initialize()
    print("AFONDO preanalysis worker started (rights-gated, max 5 per cycle)",flush=True)
    while True:
        try:
            output = process_once(limit=5, dry_run=False)
        except Exception:
            # No raw exception logging: could contain secret/provider text.
            output = {"status":"failed","detail":"Worker cycle failed"}
        output["at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(output, ensure_ascii=False), flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
