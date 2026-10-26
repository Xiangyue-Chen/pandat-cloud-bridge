from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path


mode = os.environ.get("FAKE_PANDAT_MODE", "success")
pbfx = Path(sys.argv[1]).resolve()
result = pbfx.with_suffix(".result")

if mode in {"success", "stale"}:
    source = os.environ.get("FAKE_PANDAT_RESULT_SOURCE")
    if source:
        shutil.copyfile(source, result)
    else:
        result.write_text("<result />", encoding="utf-8")
    if mode == "stale":
        old = time.time() - 3600
        os.utime(result, (old, old))
    print("Simulation is done with Success", flush=True)
    print(f"0: {result}.html", flush=True)
    time.sleep(60)
elif mode == "missing":
    print("Simulation is done with Success", flush=True)
    print(f"0: {result}.html", flush=True)
    time.sleep(60)
elif mode == "license":
    print("Failed to connect to HASP; module not activated", flush=True)
    time.sleep(60)
elif mode == "unsupported":
    print("Database does not have component Ta", flush=True)
    time.sleep(60)
elif mode == "failure":
    print("Simulation done with Failure", flush=True)
    time.sleep(60)
elif mode == "timeout":
    time.sleep(60)
elif mode == "early_exit":
    print("started then stopped", flush=True)
    raise SystemExit(7)
else:
    raise SystemExit(9)

