"""Bounded synthetic Argon2id benchmark; never prints passwords or hashes."""
import json
from concurrent.futures import ThreadPoolExecutor
from statistics import median
from time import perf_counter
import resource

from pydantic import SecretStr
from app.auth.security import HASH_CONCURRENCY, hash_password, verify_password


def main():
    value = SecretStr("Synthetic benchmark password only")
    def measure(_):
        start = perf_counter()
        encoded = hash_password(value)
        hashed = perf_counter()
        assert verify_password(value, encoded)[0]
        return hashed - start, perf_counter() - hashed
    start = perf_counter()
    with ThreadPoolExecutor(max_workers=HASH_CONCURRENCY) as pool:
        measurements = list(pool.map(measure, range(8)))
    print(json.dumps({
        "profile": "Argon2id m=65536 KiB, t=3, p=4",
        "concurrency": HASH_CONCURRENCY, "hash_verify_pairs": len(measurements),
        "median_hash_seconds": round(median(m[0] for m in measurements), 3),
        "median_verify_seconds": round(median(m[1] for m in measurements), 3),
        "total_seconds": round(perf_counter() - start, 3),
        "process_peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }, indent=2))


if __name__ == "__main__":
    main()
