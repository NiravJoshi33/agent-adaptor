"""X402Adapter — handles HTTP 402 payment-required responses.

Uses the x402 Python SDK for protocol handling (header parsing, payload encoding).
Delegates signing to the WalletPlugin (Solana or OWS).

Flow:
1. Agent makes HTTP request → gets 402 with PAYMENT-REQUIRED header
2. Adapter parses requirements, signs a payment authorization
3. Agent retries with PAYMENT-SIGNATURE header → gets 200
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from x402 import (
    PaymentRequired,
    parse_payment_required,
)

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)
from agent_adapter_contracts.wallet import WalletPlugin


class X402Adapter(PaymentAdapter):
    """Handles x402 HTTP-native payment flows.

    Parses 402 responses, creates signed payment payloads using the wallet,
    and returns headers for the retry request.
    """

    @property
    def id(self) -> str:
        return "x402"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        return challenge.type == "x402"

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        """Handle a 402 challenge end-to-end.

        Args:
            challenge: Must have headers from the 402 response.
            wallet: WalletPlugin instance for signing.

        Returns:
            PaymentReceipt with the signed payment headers for retry.
        """
        if not isinstance(wallet, WalletPlugin):
            raise TypeError("X402Adapter requires a WalletPlugin instance")

        # Parse the 402 response
        payment_required_header = challenge.headers.get(
            "payment-required", challenge.headers.get("PAYMENT-REQUIRED", "")
        )
        if not payment_required_header:
            raise ValueError("No PAYMENT-REQUIRED header in 402 response")

        # Decode and parse requirements
        try:
            raw = base64.b64decode(payment_required_header)
            payment_required = parse_payment_required(json.loads(raw))
        except Exception as e:
            raise ValueError(f"Failed to parse PAYMENT-REQUIRED header: {e}") from e

        # Extract payment details from requirements
        requirements = self._get_requirements(payment_required)
        amount = float(requirements.get("maxAmountRequired", 0))
        pay_to = requirements.get("payTo", "")
        network = requirements.get("network", "")
        resource = requirements.get("resource", "")

        # Sign the payment authorization with wallet
        wallet_address = await wallet.get_address()
        payload_data = {
            "x402Version": 2,
            "scheme": requirements.get("scheme", "exact"),
            "network": network,
            "payload": {
                "signature": "",
                "authorization": {
                    "from": wallet_address,
                    "to": pay_to,
                    "value": str(int(amount)),
                    "validAfter": "0",
                    "validBefore": str(2**48),
                    "nonce": resource,
                },
            },
        }

        # Sign the payload
        payload_bytes = json.dumps(payload_data["payload"]["authorization"]).encode()
        signature = await wallet.sign_message(payload_bytes)
        payload_data["payload"]["signature"] = signature.hex()

        # Encode as PAYMENT-SIGNATURE header
        encoded = base64.b64encode(json.dumps(payload_data).encode()).decode()
        payment_headers = {"PAYMENT-SIGNATURE": encoded}

        return PaymentReceipt(
            protocol="x402",
            amount=amount,
            currency=requirements.get("asset", "USDC"),
            tx_signature=signature.hex(),
            extra={
                "payment_headers": payment_headers,
                "network": network,
                "pay_to": pay_to,
            },
        )

    def _get_requirements(self, payment_required: Any) -> dict:
        """Extract the first set of requirements from a PaymentRequired object."""
        if hasattr(payment_required, "requirements") and payment_required.requirements:
            req = payment_required.requirements[0]
            return {
                "scheme": getattr(req, "scheme", "exact"),
                "network": getattr(req, "network", ""),
                "maxAmountRequired": getattr(req, "maxAmountRequired", "0"),
                "payTo": getattr(req, "payTo", ""),
                "resource": getattr(req, "resource", ""),
                "asset": getattr(req, "asset", "USDC"),
            }
        # V1 fallback
        if hasattr(payment_required, "scheme"):
            return {
                "scheme": payment_required.scheme,
                "network": getattr(payment_required, "network", ""),
                "maxAmountRequired": getattr(payment_required, "maxAmountRequired", "0"),
                "payTo": getattr(payment_required, "payTo", ""),
                "resource": getattr(payment_required, "resource", ""),
                "asset": getattr(payment_required, "asset", "USDC"),
            }
        raise ValueError("Cannot extract requirements from PaymentRequired")

    async def settle(self, session: PaymentSession) -> None:
        # x402 settlement is typically implicit — payment is done at call time.
        # For platforms using a facilitator, settlement happens via the facilitator.
        pass

    async def refund(self, session: PaymentSession, reason: str) -> None:
        # x402 refunds are protocol-dependent and may not be supported.
        raise NotImplementedError("x402 refunds not yet supported")
