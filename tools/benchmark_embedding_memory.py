"""Compare legacy and compact loading in separate processes on synthetic data."""
from array import array
import hashlib
import json
from pathlib import Path
import random
import resource
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai.embedding_cache import load_vectors, save_vectors  # noqa: E402


def measure(mode, path):
    start = time.perf_counter()
    if mode == "legacy":
        with open(path) as stream:
            values = json.load(stream)
    else:
        values = load_vectors(path)
    seconds = time.perf_counter() - start
    digest = hashlib.sha256()
    heap = sys.getsizeof(values)
    for key, vector in values.items():
        digest.update(array("d", vector).tobytes())
        heap += sys.getsizeof(key) + sys.getsizeof(vector)
        if isinstance(vector, list):
            heap += sum(sys.getsizeof(v) for v in vector)
    rss = next(int(line.split()[1])*1024 for line in Path("/proc/self/status").read_text().splitlines()
               if line.startswith("VmRSS:"))
    print(json.dumps({"mode": mode, "vectors": len(values), "sha256": digest.hexdigest(),
                      "heap_bytes": heap, "rss_bytes": rss, "load_seconds": seconds,
                      "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}))


if __name__ == "__main__":
    if len(sys.argv) == 3:
        measure(sys.argv[1], sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix="synthetic-embedding-audit-") as directory:
            path = Path(directory) / "vectors.json"
            rng = random.Random(20261024)
            values = {str(i): array("d", (rng.uniform(-1, 1) for _ in range(1536))) for i in range(1000)}
            save_vectors(path, values)
            del values
            results = [json.loads(subprocess.check_output([sys.executable, __file__, mode, str(path)]))  # noqa: S603
                       for mode in ("legacy", "compact")]
            if results[0]["sha256"] != results[1]["sha256"]:
                raise RuntimeError("Float values changed")
            if results[1]["heap_bytes"] / results[0]["heap_bytes"] > 0.3:
                raise RuntimeError("Compact vectors no longer meet the memory budget")
            print(json.dumps({"synthetic": True, "dimensions": 1536, "results": results}, indent=2))
