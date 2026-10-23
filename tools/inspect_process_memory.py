"""Read-only Linux memory snapshot; no credentials, DB content or command lines."""
import json
import os
from pathlib import Path


def snapshot():
    processes = []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = {}
            for line in (directory / "status").read_text().splitlines():
                key, _, value = line.partition(":")
                if key in ("VmRSS", "VmHWM", "RssAnon", "RssFile", "RssShmem"):
                    fields[key + "_bytes"] = int(value.split()[0]) * 1024
            processes.append({"pid": int(directory.name), "name": (directory / "comm").read_text().strip(), **fields})
        except (OSError, ValueError):
            continue
    cgroup = Path("/sys/fs/cgroup")
    memory = {}
    for name in ("memory.current", "memory.max", "memory.stat", "memory.events"):
        try:
            memory[name] = (cgroup / name).read_text().strip()
        except OSError:
            pass
    cache = Path(os.environ.get("STATS_DIR", ".")) / "ai_rag_embeddings_cache.json"
    try:
        cache_bytes = cache.stat().st_size
    except OSError:
        cache_bytes = None
    return {"processes": sorted(processes, key=lambda p: -p.get("VmRSS_bytes", 0)),
            "cgroup": memory, "embedding_cache_disk_bytes": cache_bytes}


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))
