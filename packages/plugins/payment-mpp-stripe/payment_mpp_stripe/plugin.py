"""Stripe-backed MPP payment adapter.

Implements the server-side Stripe "charge" intent flow described by:
- https://docs.stripe.com/payments/machine/mpp.md
- https://paymentauth.org/draft-httpauth-payment-00.txt
- https://paymentauth.org/draft-stripe-charge-00.txt
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)

STRIPE_MPP_API_VERSION = "2026-03-04.preview"
_STRIPE_API_BASE = "https://api.stripe.com"


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_decode_json(value: str) -> dict[str, Any]:
    return json.loads(_b64url_decode(value).decode())


def _b64url_encode_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse_payment_challenge_header(header_value: str) -> dict[str, str]:
    if not header_value:
        raise ValueError("Missing WWW-Authenticate Payment challenge")
    scheme, _, params = header_value.partition(" ")
    if scheme.lower() != "payment":
        raise ValueError("Unsupported auth scheme in challenge header")

    parsed: dict[str, str] = {}
    current = ""
    parts: list[str] = []
    in_quotes = False
    for char in params:
        if char == '"':
            in_quotes = not in_quotes
        if char == "," and not in_quotes:
            if current.strip():
                parts.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        parts.append(current.strip())

    for item in parts:
        key, sep, value = item.partition("=")
        if not sep:
            continue
        parsed[key.strip()] = _strip_quotes(value.strip())
    if not parsed:
        raise ValueError("Malformed WWW-Authenticate Payment challenge")
    return parsed


def parse_payment_authorization_header(header_value: str) -> dict[str, Any]:
    if not header_value:
        raise ValueError("Missing Authorization Payment credential")
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "payment" or not token:
        raise ValueError("Unsupported Authorization scheme for MPP")
    return _b64url_decode_json(token.strip())


def build_payment_receipt_header(payload: dict[str, Any]) -> str:
    return _b64url_encode_json(payload)


class MPPStripeAdapter(PaymentAdapter):
    def __init__(
        self,
        secret_key: str | None = None,
        shared_payment_token: str | None = None,
        external_id: str | None = None,
        api_base: str = _STRIPE_API_BASE,
        api_version: str = STRIPE_MPP_API_VERSION,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._shared_payment_token = shared_payment_token
        self._external_id = external_id
        self._api_base = api_base.rstrip("/")
        self._api_version = api_version
        self._owns_client = http_client is None
        auth = (secret_key, "") if secret_key else None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._api_base,
            timeout=30,
            auth=auth,
            headers={"Stripe-Version": api_version},
        )

    @property
    def id(self) -> str:
        return "stripe_mpp"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        if challenge.type not in {"mpp", "mpp_stripe", "stripe_mpp", "stripe"}:
            return False
        method = str(
            (challenge.extra or {}).get("payment_method", "")
            or (challenge.extra or {}).get("method", "")
        ).lower()
        if method and method != "stripe":
            return False
        return True

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        if self._has_client_credentials(challenge):
            return self._build_client_authorization_receipt(challenge)
        if not self._secret_key:
            raise ValueError(
                "MPP Stripe settlement requires secret_key or client-side shared_payment_token"
            )
        challenge_obj, request_obj = self._resolve_challenge(challenge)
        credential = self._resolve_credential(challenge)
        self._verify_challenge_binding(challenge_obj, request_obj, credential)

        payload = credential.get("payload") or {}
        spt = str(payload.get("spt") or "")
        if not spt.startswith("spt_"):
            raise ValueError("MPP Stripe credential payload is missing a valid spt")

        form = self._build_payment_intent_form(challenge_obj, request_obj, payload)
        response = await self._client.post(
            "/v1/payment_intents",
            data=form,
            headers={"Idempotency-Key": f"{challenge_obj['id']}_{spt}"},
        )
        response.raise_for_status()
        payment_intent = response.json()

        if payment_intent.get("status") != "succeeded":
            raise ValueError(
                f"Stripe PaymentIntent did not succeed: {payment_intent.get('status')}"
            )

        receipt_payload = {
            "method": "stripe",
            "reference": payment_intent["id"],
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        external_id = payload.get("externalId")
        if external_id:
            receipt_payload["externalId"] = external_id

        amount = (
            challenge.amount
            if challenge.amount
            else float(request_obj.get("amount", 0) or 0) / 100
        )
        return PaymentReceipt(
            protocol="mpp",
            amount=amount,
            currency=str(request_obj.get("currency", "usd")).upper(),
            tx_signature=payment_intent["id"],
            extra={
                "method": "stripe",
                "payment_intent_id": payment_intent["id"],
                "payment_intent_status": payment_intent.get("status"),
                "receipt": receipt_payload,
                "payment_receipt_header": build_payment_receipt_header(receipt_payload),
                "challenge_id": challenge_obj["id"],
                "spt": spt,
            },
        )

    async def settle(self, session: PaymentSession) -> None:
        return None

    async def refund(self, session: PaymentSession, reason: str) -> None:
        payment_intent_id = ""
        if session.receipt:
            payment_intent_id = str(session.receipt.extra.get("payment_intent_id", ""))
        if not payment_intent_id:
            payment_intent_id = str(session.challenge.extra.get("payment_intent_id", ""))
        if not payment_intent_id:
            raise ValueError("Refund requires a Stripe PaymentIntent reference")

        refund_reason = (
            reason
            if reason in {"duplicate", "fraudulent", "requested_by_customer"}
            else "requested_by_customer"
        )
        form = {
            "payment_intent": payment_intent_id,
            "reason": refund_reason,
            "metadata[adapter_reason]": reason,
        }
        response = await self._client.post("/v1/refunds", data=form)
        response.raise_for_status()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _has_client_credentials(self, challenge: PaymentChallenge) -> bool:
        auth_header = (
            challenge.headers.get("Authorization")
            or challenge.headers.get("authorization")
            or challenge.extra.get("authorization")
            or challenge.extra.get("authorization_header")
        )
        if auth_header:
            return False
        token = (
            challenge.extra.get("shared_payment_token")
            or challenge.extra.get("spt")
            or self._shared_payment_token
        )
        return bool(token)

    def _build_client_authorization_receipt(
        self, challenge: PaymentChallenge
    ) -> PaymentReceipt:
        challenge_obj, request_obj = self._resolve_challenge(challenge)
        shared_payment_token = str(
            challenge.extra.get("shared_payment_token")
            or challenge.extra.get("spt")
            or self._shared_payment_token
            or ""
        )
        if not shared_payment_token.startswith("spt_"):
            raise ValueError("MPP client flow requires a valid shared_payment_token")
        payload: dict[str, Any] = {"spt": shared_payment_token}
        external_id = (
            challenge.extra.get("external_id")
            or challenge.extra.get("externalId")
            or self._external_id
        )
        if external_id:
            payload["externalId"] = str(external_id)
        credential = {
            "challenge": challenge_obj,
            "payload": payload,
        }
        authorization_header = "Payment " + build_payment_receipt_header(credential)
        return PaymentReceipt(
            protocol="mpp",
            amount=challenge.amount or float(request_obj.get("amount", 0) or 0) / 100,
            currency=str(request_obj.get("currency", "usd")).upper(),
            extra={
                "method": "stripe",
                "authorization_header": authorization_header,
                "challenge_id": challenge_obj["id"],
                "credential": credential,
            },
        )

    def _resolve_challenge(
        self, challenge: PaymentChallenge
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        challenge_obj = challenge.extra.get("challenge")
        if challenge_obj is None:
            header_value = (
                challenge.headers.get("WWW-Authenticate")
                or challenge.headers.get("www-authenticate")
                or challenge.extra.get("www_authenticate")
                or challenge.extra.get("challenge_header")
            )
            if not header_value:
                raise ValueError("MPP challenge is missing challenge metadata")
            challenge_obj = parse_payment_challenge_header(str(header_value))

        if str(challenge_obj.get("method", "")).lower() != "stripe":
            raise ValueError("MPP Stripe adapter only supports method='stripe'")
        if str(challenge_obj.get("intent", "")).lower() != "charge":
            raise ValueError("MPP Stripe adapter only supports intent='charge'")

        request_raw = str(challenge_obj.get("request", "") or "")
        if not request_raw:
            raise ValueError("MPP challenge is missing request payload")
        request_obj = _b64url_decode_json(request_raw)
        return challenge_obj, request_obj

    def _resolve_credential(self, challenge: PaymentChallenge) -> dict[str, Any]:
        credential = challenge.extra.get("credential")
        if credential is not None:
            return credential

        auth_header = (
            challenge.headers.get("Authorization")
            or challenge.headers.get("authorization")
            or challenge.extra.get("authorization")
            or challenge.extra.get("authorization_header")
        )
        if not auth_header:
            raise ValueError("MPP execution requires a Payment credential")
        return parse_payment_authorization_header(str(auth_header))

    def _verify_challenge_binding(
        self,
        challenge_obj: dict[str, Any],
        request_obj: dict[str, Any],
        credential: dict[str, Any],
    ) -> None:
        embedded = credential.get("challenge") or {}
        if str(embedded.get("id", "")) != str(challenge_obj.get("id", "")):
            raise ValueError("MPP credential challenge ID does not match")
        for field in ("method", "intent", "realm", "request"):
            left = embedded.get(field)
            right = challenge_obj.get(field)
            if left is not None and str(left) != str(right):
                raise ValueError(f"MPP credential mismatch for challenge field: {field}")

        expires = challenge_obj.get("expires") or embedded.get("expires")
        if expires:
            expires_at = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if expires_at <= datetime.now(timezone.utc):
                raise ValueError("MPP challenge has expired")

        request_currency = str(request_obj.get("currency", "")).lower()
        if not request_currency:
            raise ValueError("MPP request is missing currency")
        if not str(request_obj.get("amount", "")).isdigit():
            raise ValueError("MPP request amount must be a string in smallest units")

        method_details = request_obj.get("methodDetails") or {}
        network_id = method_details.get("networkId")
        embedded_request = (
            _b64url_decode_json(str(embedded["request"]))
            if embedded.get("request")
            else request_obj
        )
        if str(embedded_request.get("amount", "")) != str(request_obj.get("amount", "")):
            raise ValueError("MPP credential amount does not match challenge")
        if str(embedded_request.get("currency", "")).lower() != request_currency:
            raise ValueError("MPP credential currency does not match challenge")
        embedded_details = embedded_request.get("methodDetails") or {}
        if network_id and embedded_details.get("networkId") != network_id:
            raise ValueError("MPP credential network does not match challenge")

    def _build_payment_intent_form(
        self,
        challenge_obj: dict[str, Any],
        request_obj: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, str]:
        form: dict[str, str] = {
            "amount": str(request_obj["amount"]),
            "currency": str(request_obj["currency"]).lower(),
            "shared_payment_granted_token": str(payload["spt"]),
            "confirm": "true",
            "automatic_payment_methods[enabled]": "true",
            "automatic_payment_methods[allow_redirects]": "never",
            "metadata[challenge_id]": str(challenge_obj["id"]),
        }
        if request_obj.get("description"):
            form["description"] = str(request_obj["description"])
        external_id = payload.get("externalId") or request_obj.get("externalId")
        if external_id:
            form["metadata[external_id]"] = str(external_id)
        method_details = request_obj.get("methodDetails") or {}
        metadata = method_details.get("metadata") or {}
        for key, value in metadata.items():
            form[f"metadata[{key}]"] = str(value)
        return form
