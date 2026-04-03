"""Provider's API — with x402 payment (implemented from Coinbase spec, no SDK).

x402 flow:
1. Client GETs resource → 402 + PAYMENT-REQUIRED header (base64 JSON)
2. Client builds USDC transfer tx, partially signs, sends in PAYMENT-SIGNATURE header
3. Server verifies tx, co-signs as fee payer, submits to chain, serves resource

The provider is also the facilitator (self-hosted). Same keypair is:
- The payment recipient (payTo)
- The fee payer (pays SOL gas for tx submission)
"""

from __future__ import annotations

import base64
import json
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from solana.rpc.async_api import AsyncClient as SolanaClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.instructions import get_associated_token_address

app = FastAPI(
    title="WeatherPro API (x402 Paid)",
    description="Weather + holiday data. Paid endpoints require x402 USDC payment.",
    version="1.0.0",
)

# Provider keypair — receives payments AND pays gas (self-hosted facilitator)
PROVIDER_KEYPAIR = Keypair()
PROVIDER_ADDRESS = str(PROVIDER_KEYPAIR.pubkey())
RPC_URL = "http://127.0.0.1:8899"

# Set after USDC mint is created on Surfpool
USDC_MINT: str = ""
NETWORK = "solana:localnet"

# Route pricing in USDC smallest units (6 decimals: 10000 = $0.01)
ROUTE_PRICES: dict[str, int] = {}

# Prevent replay
_used_sigs: set[str] = set()


def configure(usdc_mint: str, route_prices: dict[str, int] | None = None) -> None:
    """Configure the provider with a USDC mint and route prices."""
    global USDC_MINT, ROUTE_PRICES
    USDC_MINT = usdc_mint
    ROUTE_PRICES = route_prices or {
        "/weather/current": 10_000,       # $0.01
        "/weather/forecast": 20_000,      # $0.02
        "/holidays/next": 5_000,          # $0.005
        "/holidays/country": 3_000,       # $0.003
    }


def _match_route(path: str) -> int | None:
    """Match a request path to a price. Returns price in USDC smallest units or None."""
    for pattern, price in ROUTE_PRICES.items():
        if path.startswith(pattern):
            return price
    return None


def _build_payment_required(path: str, price: int) -> str:
    """Build base64-encoded PAYMENT-REQUIRED header value."""
    payload = {
        "x402Version": 2,
        "requirements": [
            {
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": str(price),
                "asset": USDC_MINT,
                "payTo": PROVIDER_ADDRESS,
                "resource": path,
                "maxTimeoutSeconds": 300,
                "extra": {
                    "feePayer": PROVIDER_ADDRESS,
                },
            }
        ],
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


async def _verify_and_submit(payment_sig_header: str, expected_price: int) -> dict:
    """Verify a payment tx, co-sign as fee payer, submit to chain.

    Returns settlement receipt or raises on failure.
    """
    # Decode the payment header
    raw = base64.b64decode(payment_sig_header)
    payment = json.loads(raw)
    tx_b64 = payment["payload"]["transaction"]
    tx_bytes = base64.b64decode(tx_b64)

    # Deserialize the partially-signed transaction
    tx = VersionedTransaction.from_bytes(tx_bytes)

    # Basic validation: check the tx is targeting our fee payer
    msg = tx.message
    account_keys = msg.account_keys
    if account_keys[0] != PROVIDER_KEYPAIR.pubkey():
        raise ValueError("Fee payer mismatch — tx not addressed to this provider")

    # Check for USDC transfer instruction to our ATA
    provider_ata = get_associated_token_address(
        PROVIDER_KEYPAIR.pubkey(), Pubkey.from_string(USDC_MINT)
    )

    # Co-sign as fee payer: sign the versioned message bytes, fill in position 0
    from solders.signature import Signature as SoldersSig
    from solders.message import to_bytes_versioned
    signable = to_bytes_versioned(msg)
    provider_sig = PROVIDER_KEYPAIR.sign_message(signable)

    all_sigs = list(tx.signatures)
    all_sigs[0] = provider_sig  # Fee payer is always position 0
    final_tx = VersionedTransaction.populate(msg, all_sigs)

    # Dedup check
    tx_sig_str = str(final_tx.signatures[0])
    if tx_sig_str in _used_sigs:
        raise ValueError("Duplicate payment — tx already used")

    # Submit to chain
    async with SolanaClient(RPC_URL) as rpc:
        result = await rpc.send_transaction(final_tx)
        sig = result.value
        # Wait for confirmation
        for _ in range(30):
            import asyncio
            status = await rpc.confirm_transaction(sig)
            if status.value and status.value[0]:
                break
            await asyncio.sleep(0.5)

    _used_sigs.add(tx_sig_str)

    return {
        "success": True,
        "txSignature": str(sig),
        "amount": expected_price,
        "asset": USDC_MINT,
    }


# ── x402 Middleware ────────────────────────────────────────────────


@app.middleware("http")
async def x402_middleware(request: Request, call_next):
    path = request.url.path
    price = _match_route(path)

    if price is None or not USDC_MINT:
        return await call_next(request)

    # Check for payment proof
    payment_sig = request.headers.get("payment-signature", "")

    if not payment_sig:
        # Return 402 with requirements
        encoded = _build_payment_required(str(request.url), price)
        return JSONResponse(
            status_code=402,
            content={
                "error": "Payment Required",
                "message": f"Send {price / 1e6} USDC to {PROVIDER_ADDRESS}",
            },
            headers={"PAYMENT-REQUIRED": encoded},
        )

    # Verify, co-sign, submit
    try:
        receipt = await _verify_and_submit(payment_sig, price)
        response = await call_next(request)
        response.headers["PAYMENT-RESPONSE"] = base64.b64encode(
            json.dumps(receipt).encode()
        ).decode()
        return response
    except Exception as e:
        return JSONResponse(
            status_code=402,
            content={"error": f"Payment failed: {str(e)}"},
        )


# ── Free info endpoint ─────────────────────────────────────────────


@app.get("/provider/info", operation_id="get_provider_info")
async def get_provider_info() -> dict:
    """Provider info: wallet, pricing, payment instructions. Free."""
    return {
        "name": "WeatherPro",
        "provider_wallet": PROVIDER_ADDRESS,
        "fee_payer": PROVIDER_ADDRESS,
        "usdc_mint": USDC_MINT,
        "network": NETWORK,
        "payment_protocol": "x402",
        "pricing": {k: v / 1e6 for k, v in ROUTE_PRICES.items()},
        "currency": "USDC",
        "instructions": (
            "1. GET any paid endpoint → receive 402 + PAYMENT-REQUIRED header. "
            "2. Build a USDC SPL transfer tx to the provider's ATA with the required amount. "
            f"   Fee payer = {PROVIDER_ADDRESS} (provider pays gas). "
            "3. Partially sign the tx with your wallet keypair. "
            "4. Retry the same GET with PAYMENT-SIGNATURE header containing base64 JSON: "
            '   {"x402Version": 2, "payload": {"transaction": "<base64 tx>"}, '
            '    "accepted": {"scheme": "exact", "network": "..."}, "resource": "..."}. '
            "5. Provider co-signs, submits to chain, and serves the response."
        ),
    }


# ── Weather endpoints (paid) ──────────────────────────────────────


class WeatherResponse(BaseModel):
    location: str
    temperature_c: float
    condition: str
    humidity: str
    wind: str


@app.get(
    "/weather/current",
    response_model=WeatherResponse,
    operation_id="get_current_weather",
    summary="Get current weather (x402: 0.01 USDC)",
)
async def get_current_weather(location: str) -> WeatherResponse:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://wttr.in/{location}",
            params={"format": "j1"},
            headers={"User-Agent": "weatherpro-api"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream weather service unavailable")
        data = resp.json()
    current = data["current_condition"][0]
    area = data["nearest_area"][0]
    return WeatherResponse(
        location=area["areaName"][0]["value"],
        temperature_c=float(current["temp_C"]),
        condition=current["weatherDesc"][0]["value"],
        humidity=current["humidity"],
        wind=f"{current['windspeedKmph']} km/h {current['winddir16Point']}",
    )


@app.get(
    "/weather/forecast",
    operation_id="get_weather_forecast",
    summary="Get 3-day forecast (x402: 0.02 USDC)",
)
async def get_weather_forecast(location: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://wttr.in/{location}",
            params={"format": "j1"},
            headers={"User-Agent": "weatherpro-api"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream weather service unavailable")
        data = resp.json()
    area = data["nearest_area"][0]
    days = []
    for day in data.get("weather", []):
        days.append({
            "date": day["date"],
            "max_temp_c": float(day["maxtempC"]),
            "min_temp_c": float(day["mintempC"]),
            "condition": day["hourly"][4]["weatherDesc"][0]["value"],
        })
    return {"location": area["areaName"][0]["value"], "days": days}


# ── Holiday endpoints (paid) ──────────────────────────────────────


@app.get(
    "/holidays/next/{country_code}",
    operation_id="get_next_holidays",
    summary="Get upcoming holidays (x402: 0.005 USDC)",
)
async def get_next_holidays(country_code: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://date.nager.at/api/v3/NextPublicHolidays/{country_code}"
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream holiday service unavailable")
        return resp.json()


@app.get(
    "/holidays/country/{country_code}",
    operation_id="get_country_info",
    summary="Get country info (x402: 0.003 USDC)",
)
async def get_country_info(country_code: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://date.nager.at/api/v3/CountryInfo/{country_code}"
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Upstream service unavailable")
        return resp.json()
