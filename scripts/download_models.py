from __future__ import annotations

import argparse
import sys

from precache_lite_models import main as precache_lite_main
from verify_models import main as verify_models_main


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy compatibility wrapper. Use scripts/precache_lite_models.py "
            "for public Lite models and scripts/verify_models.py for artifact checks."
        )
    )
    parser.add_argument("--verify-only", action="store_true", help="Run verify_models.py instead of pre-cache.")
    args, rest = parser.parse_known_args()

    if args.verify_only:
        sys.argv = ["verify_models.py", *rest]
        return verify_models_main()

    print(
        "download_models.py is a compatibility wrapper. "
        "Prefer: python scripts\\precache_lite_models.py --model medium"
    )
    sys.argv = ["precache_lite_models.py", *rest]
    return precache_lite_main()


if __name__ == "__main__":
    raise SystemExit(main())
