"""x402-aware HTTP client — wraps httpx.AsyncClient with automatic 402 handling.

When a request returns 402:
1. Parses PAYMENT-REQUIRED header
2. Builds USDC transfer tx using the agent's keypair
3. Partially signs the tx (server co-signs and submits)
4. Retries with PAYMENT-SIGNATURE header
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from solders.keypair import Keypair

from payment_x402.plugin import (
    parse_402_requirements,
    build_payment_tx,
    encode_payment_header,
)

logger = logging.getLogger(__name__)


class X402HttpClient:
    """httpx.AsyncClient wrapper that handles x402 payment automatically."""

    def __init__(
        self,
        keypair: Keypair,
        rpc_url: str = "http://127.0.0.1:8899",
        **httpx_kwargs: Any,
    ) -> None:
        self._keypair = keypair
        self._rpc_url = rpc_url
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            **httpx_kwargs,
        )

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request. If 402, auto-handle payment and retry."""
        resp = await self._client.request(method, url, **kwargs)

        if resp.status_code != 402:
            return resp

        # Parse 402 requirements
        logger.info("Got 402 from %s — processing x402 payment", url)
        try:
            requirements = parse_402_requirements(dict(resp.headers))
        except Exception as e:
            logger.error("Failed to parse 402 requirements: %s", e)
            return resp

        # Build and sign payment tx
        logger.info(
            "Building USDC transfer: %s units to %s",
            requirements.get("maxAmountRequired"),
            requirements.get("payTo"),
        )
        tx_bytes = await build_payment_tx(
            self._keypair, requirements, self._rpc_url
        )

        # Encode payment header
        payment_header = encode_payment_header(
            tx_bytes, requirements, str(url)
        )

        # Retry with payment proof
        headers = dict(kwargs.get("headers", {}))
        headers["PAYMENT-SIGNATURE"] = payment_header
        kwargs["headers"] = headers

        logger.info("Retrying %s %s with payment proof", method, url)
        return await self._client.request(method, url, **kwargs)

    # Convenience methods
    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()
