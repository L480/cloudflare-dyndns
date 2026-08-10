from __future__ import annotations

import uvicorn

from cloudflare_dyndns.app import create_app
from cloudflare_dyndns.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
