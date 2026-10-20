"""Optional operator-enabled RSS/API metadata discovery worker.

This never acquires full article text and cannot scan unlicensed sources.
Publisher cooldowns, exact host pinning and rights grants apply at every sync.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from afondo.sync_sources import run

MIN_INTERVAL_SECONDS = 3600


def main() -> None:
    if os.getenv("AFONDO_ENABLE_SOURCE_SYNC") != "1":
        raise SystemExit("Source metadata worker disabled; opt in explicitly")
    try:
        interval = int(os.getenv("AFONDO_SOURCE_SYNC_INTERVAL_SECONDS", "3600"))
    except ValueError as exc:
        raise SystemExit("Invalid source scan interval") from exc
    if interval < MIN_INTERVAL_SECONDS:
        raise SystemExit("Source scan interval must be >= 3600 seconds")
    print("AFONDO metadata-only licensed discovery worker started", flush=True)
    while True:
        try:
            code = run(dry_run=False)
        except Exception:
            code = 1
        print(json.dumps({
            "worker": "source-metadata", "status": "ok" if code == 0 else "some_sources_failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
