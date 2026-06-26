from __future__ import annotations

import argparse
import json

from app.services.bando_discovery_service import BandoDiscoveryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan livello 2 fonti e identifica bandi")
    parser.add_argument("--limit", type=int, default=None, help="Numero massimo di fonti da scansionare")
    args = parser.parse_args()

    service = BandoDiscoveryService()
    result = service.run(limit=args.limit)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
