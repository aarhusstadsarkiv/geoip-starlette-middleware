from functools import lru_cache
from pathlib import Path

import geoip2.database
import geoip2.errors
import starlette.types

__all__ = ["GeoIPMiddleware"]


class GeoIPMiddleware:
    def __init__(
        self,
        app: starlette.types.ASGIApp,
        *,
        database_path: str | Path | None,
        allowed_countries: list[str] | None = None,
        blocked_countries: list[str] | None = None,
        allowed_addresses: list[str] | None = None,
        blocked_addresses: list[str] | None = None,
    ):
        self.app: starlette.types.ASGIApp = app
        self.database: geoip2.database.Reader | None = geoip2.database.Reader(database_path) if database_path else None
        self.allowed_countries: set[str] = {c_ for c in allowed_countries or [] if (c_ := c.strip().lower())}
        self.blocked_countries: set[str] = {c_ for c in blocked_countries or [] if (c_ := c.strip().lower())}
        self.allowed_addresses: set[str] = {a_ for a in allowed_addresses or [] if (a_ := a.strip())}
        self.blocked_addresses: set[str] = {a_ for a in blocked_addresses or [] if (a_ := a.strip())}
        self.__empty = not self.database or (
            not self.allowed_countries
            and not self.blocked_countries
            and not self.allowed_addresses
            and not self.blocked_addresses
        )

    @lru_cache
    def get_address_country(self, address: str) -> str | None:
        if not self.database:
            return None

        try:
            response = self.database.country(address)
            return c.lower() if (c := response.country.iso_code) else None
        except geoip2.errors.AddressNotFoundError:
            return None

    @lru_cache
    def is_allowed(self, address: str | None) -> bool:
        if address is None:
            return False
        if self.allowed_addresses and address in self.allowed_addresses:
            return True
        if self.blocked_addresses and address in self.blocked_addresses:
            return False
        if self.allowed_countries:
            return self.get_address_country(address) in self.allowed_countries
        if self.blocked_countries:
            return self.get_address_country(address) not in self.blocked_countries
        return True

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send
    ):
        if not self.__empty and scope["type"] == "http":
            # scope["client"] is a tuple (host, port) or None
            client_host, _ = scope["client"] or (None, None)
            if not self.is_allowed(client_host):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                return

        await self.app(scope, receive, send)
