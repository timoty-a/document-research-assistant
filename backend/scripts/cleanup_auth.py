"""One guarded, bounded cleanup batch; never removes a valid session."""
import argparse
from app.auth.service import AuthError, cleanup, utcnow
from app.config import Settings
from app.db import create_db_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, choices=range(1, 1001), default=500, metavar="1..1000")
    args = parser.parse_args()
    settings = Settings()
    engine = create_db_engine(settings)
    try:
        counts = cleanup(engine, settings, utcnow, args.batch_size)
        print(f"Removed {counts['sessions']} expired/revoked sessions and {counts['rate_limits']} old counters")
    except AuthError:
        raise SystemExit("Cleanup failed; check database identity, access and migration status") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
