from __future__ import annotations

import json

from app.services.fonte_discovery_service import FonteDiscoveryService


def main() -> None:
    service = FonteDiscoveryService()
    result = service.run()
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
