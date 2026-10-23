# Railway memory optimization — 24 October 2026

The first change reduces VMEDA's resident embedding cache without changing the
embedding model, precision, dimensions, retrieval scores or subscription logic.
Every historical cache key is retained. No users, payments, learning progress,
orders, subscriptions, databases or volumes are removed or migrated.

## Measured offline result

Python 3.12; 1,000 synthetic vectors of 1,536 unique random float64 values;
separate subprocess for each loader. This is NOT a production RAM measurement.
The SHA-256 of every float64 byte in order is identical before and after.

| Metric | Legacy | Compact |
| --- | ---: | ---: |
| Vector dictionary heap, bytes | 49,661,922 | 12,437,922 |
| Process RSS after load, bytes | 73,502,720 | 25,923,584 |
| Process peak RSS, bytes | 105,234,432 | 25,952,256 |
| Load time, seconds | 0.490 | 0.579 |

Vector storage shrinks about 75%. The offline cache load is about 0.09 seconds
slower per 1,000 vectors in this sample; request scoring uses the same arithmetic
and values. Startup still needs a live timing check before a production rollout.
The streaming loader avoids materializing the entire source JSON text and all
Python float lists at once. Writes preserve the old JSON format, use one temporary
list at a time, fsync the temporary file and atomically replace the old cache.
An older release can read the resulting file; no paid vector rebuild is required.

At the previously observed $10/GB-month RAM rate, 1,000 resident vectors save
about $0.37/month in vector storage; 10,000 save about $3.72/month. Actual invoice
savings depend on real cache size, residency, billing units and deployment time.
Do not claim this is a 75% reduction in the whole bot or total Railway invoice.

## Validation

- `python3 tests/test_embedding_memory.py`: eight offline regression tests.
- Exact float bits, cosine values and ranking preserved.
- Legacy cache read and old-loader-compatible JSON write checked.
- Historical keys retained; repeated build does not purchase existing vectors.
- Tiny read boundaries, malformed files and empty dictionaries checked.
- Replacement/serialization failure leaves the old file unchanged and removes
  temporary files.
- `python3 tools/benchmark_embedding_memory.py`: deterministic memory budget and
  float checksum test, with JSON output.
- Full bot/API/synchronization CI must pass before production deployment.

## Production rollout and further savings

Railway access was unavailable during the preceding audit; no new live metrics,
volume backup or service configuration verification is claimed here. No service
has been stopped and no production configuration has been changed by this patch.
Keep this work on a separate branch until deployment prerequisites are verified.

1. Capture `python3 tools/inspect_process_memory.py` in the running container and
   Railway RAM/CPU metrics. It reads process RSS, anonymous/file-backed memory,
   cgroup memory and cache file size without reading database contents or secrets.
2. Verify the existing persistent `/data` volume, backup and single bot instance.
   Roll out through the normal deployment process; do not start a second poller.
3. Compare steady RAM and response latency under similar traffic over 24 hours;
   check bot polling, miniapp synchronization, subscription access and payments.
4. If rollback is necessary, deploy the previous code against the same data and
   cache. Do not restore stale user statistics over recent activity.
5. Profile VICEGRAM OCR/PDF concurrency and native allocations separately. Retain
   its owner data. A bounded queue and short-lived workers are candidates, not
   measured savings yet.
6. Review additional Trade workers individually for redundant functionality;
   do not stop active services or delete their databases just to meet a budget.

Historical 19 October averages: VMEDA bot 1.060 GB, VICEGRAM 1.103 GB, VMEDA API
0.225 GB, frontend 0.060 GB. These are NOT current measurements. The prior VICEGRAM
media cleanup primarily reduced disk costs (~$0.45–0.48/month at the old rate),
not a demonstrated reduction in RAM. Do not set a lower RAM cap, enable sleeping
for the Telegram polling bot, disable backups, delete statistics or schedule
restarts as a substitute for correcting memory use.
