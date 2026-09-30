"""Frozen app launcher; keep mutable data outside the executable bundle."""

import json
import os
import shutil
import sys
from pathlib import Path

from hots_draft import main

if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--apply-update":
        from hots_draft.updater import apply_update

        raise SystemExit(
            apply_update(
                Path(sys.argv[2]),
                int(sys.argv[3]),
                json.loads(sys.argv[4]),
                Path(sys.argv[5]),
            )
        )
    if "--skip-update-once" in sys.argv:
        sys.argv.remove("--skip-update-once")
        sys.argv.append("--no-update")
    if getattr(sys, "frozen", False) and not any(
        arg == "--data-dir" or arg.startswith("--data-dir=") for arg in sys.argv[1:]
    ):
        data_home = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")
        )
        destination = data_home / "HotsDraft" / "data"
        legacy_session = data_home / "NexusDraft" / "data" / "draft-session.json"
        if (
            legacy_session.exists()
            and not (destination / "draft-session.json").exists()
        ):
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_session, destination / "draft-session.json")
        sys.argv.extend(["--data-dir", str(destination)])
    main()
