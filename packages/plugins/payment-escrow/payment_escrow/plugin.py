"""Generic Solana escrow adapter for platform-supplied program payloads.

The adapter does not own or assume a local program/IDL. Instead, the target
platform supplies either:

1. A fully prepared unsigned transaction, or
2. Instruction payloads (program id, account metas, encoded data) that can be
   compiled into a transaction locally.

The runtime then validates signer requirements, signs with the active wallet,
submits to the configured RPC, and can poll confirmation status.
"""

from __future__ import annotations

import base64
from typing import Any, Callable

from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.types import TxOpts
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)


class EscrowAdapter(PaymentAdapter):
    """Generic Solana transaction adapter for escrow-style platform payments."""

    def __init__(
        self,
        rpc_url: str = "http://127.0.0.1:8899",
        rpc_client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._rpc_url = rpc_url
        self._rpc_client_factory = rpc_client_factory or SolanaClient

    @property
    def id(self) -> str:
        return "solana_escrow"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        return challenge.type == "escrow"

    async def prepare_lock(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> dict[str, Any]:
        payload = challenge.extra or {}
        if "unsigned_transaction" in payload:
            tx_bytes = self._decode_bytes(
                payload["unsigned_transaction"],
                payload.get("transaction_encoding", "base64"),
            )
        else:
            tx_bytes = await self._build_unsigned_transaction(payload, wallet)

        wallet_address = await wallet.get_address()
        signer_info = self._required_signers(tx_bytes)
        unsupported = [s for s in signer_info if s != wallet_address]
        if unsupported:
            raise ValueError(
                "Escrow payload requires additional signers not controlled by the runtime: "
                + ", ".join(unsupported)
            )

        return {
            "transaction": base64.b64encode(tx_bytes).decode(),
            "encoding": "base64",
            "network": payload.get("network", "solana"),
            "amount": challenge.amount or payload.get("amount", 0.0),
            "currency": payload.get("currency", challenge.extra.get("currency", "USDC") if challenge.extra else "USDC"),
            "reference": payload.get("reference", ""),
            "required_signers": signer_info,
            "metadata": payload.get("metadata", {}),
        }

    async def sign_and_submit(
        self,
        transaction: str,
        wallet: Any,
        *,
        encoding: str = "base64",
        commitment: str = "confirmed",
    ) -> dict[str, Any]:
        tx_bytes = self._decode_bytes(transaction, encoding)
        signed_tx = await wallet.sign_transaction(tx_bytes)
        versioned = VersionedTransaction.from_bytes(signed_tx)
        signature = str(versioned.signatures[0])

        async with self._rpc_client_factory(self._rpc_url) as rpc:
            response = await rpc.send_raw_transaction(
                signed_tx,
                opts=TxOpts(skip_preflight=False, preflight_commitment=commitment),
            )
            await rpc.confirm_transaction(Signature.from_string(signature))

        return {
            "submitted": True,
            "signature": signature,
            "rpc_response": str(response.value),
            "encoding": "base64",
            "signed_transaction": base64.b64encode(signed_tx).decode(),
        }

    async def check_status(
        self,
        signature: str,
        *,
        search_transaction_history: bool = True,
    ) -> dict[str, Any]:
        async with self._rpc_client_factory(self._rpc_url) as rpc:
            response = await rpc.get_signature_statuses(
                [Signature.from_string(signature)],
                search_transaction_history=search_transaction_history,
            )

        status = response.value[0]
        if status is None:
            return {"found": False, "signature": signature}
        confirmation_status = status.confirmation_status
        if hasattr(confirmation_status, "value"):
            confirmation_status = confirmation_status.value
        confirmation_status = str(confirmation_status or "")
        if confirmation_status.startswith("TransactionConfirmationStatus."):
            confirmation_status = confirmation_status.rsplit(".", 1)[-1].lower()
        return {
            "found": True,
            "signature": signature,
            "confirmation_status": confirmation_status,
            "confirmations": status.confirmations,
            "slot": status.slot,
            "error": status.err,
        }

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        prepared = await self.prepare_lock(challenge, wallet)
        submitted = await self.sign_and_submit(
            prepared["transaction"],
            wallet,
            encoding=prepared["encoding"],
        )
        return PaymentReceipt(
            protocol="solana_escrow",
            amount=prepared["amount"],
            currency=prepared["currency"],
            tx_signature=submitted["signature"],
            extra={
                "reference": prepared["reference"],
                "required_signers": prepared["required_signers"],
                "metadata": prepared["metadata"],
            },
        )

    async def settle(self, session: PaymentSession) -> None:
        if session.receipt and session.receipt.tx_signature:
            session.status = "settled"

    async def refund(self, session: PaymentSession, reason: str) -> None:
        raise NotImplementedError(
            "Escrow refunds are platform-specific and must be initiated by the target platform."
        )

    async def _build_unsigned_transaction(
        self, payload: dict[str, Any], wallet: Any
    ) -> bytes:
        instruction_payloads = payload.get("instructions")
        if not instruction_payloads:
            single_ix = {
                "program_id": payload.get("program_id"),
                "accounts": payload.get("accounts", []),
                "data": payload.get("data", ""),
                "data_encoding": payload.get("data_encoding", "base64"),
            }
            if single_ix["program_id"]:
                instruction_payloads = [single_ix]
        if not instruction_payloads:
            raise ValueError(
                "Escrow payload must include either unsigned_transaction or instruction payloads"
            )

        fee_payer = payload.get("fee_payer") or await wallet.get_address()
        wallet_address = await wallet.get_address()
        if fee_payer != wallet_address:
            raise ValueError(
                "sign_and_submit requires the active wallet to be the fee payer"
            )
        recent_blockhash = payload.get("recent_blockhash")
        if not recent_blockhash:
            async with self._rpc_client_factory(self._rpc_url) as rpc:
                blockhash_resp = await rpc.get_latest_blockhash()
                recent_blockhash = str(blockhash_resp.value.blockhash)

        instructions = [self._instruction_from_payload(item) for item in instruction_payloads]
        msg = MessageV0.try_compile(
            payer=Pubkey.from_string(fee_payer),
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=Hash.from_string(recent_blockhash),
        )
        signatures = [Signature.default()] * msg.header.num_required_signatures
        return bytes(VersionedTransaction.populate(msg, signatures))

    def _instruction_from_payload(self, payload: dict[str, Any]) -> Instruction:
        program_id = payload.get("program_id")
        if not program_id:
            raise ValueError("Instruction payload missing program_id")
        data = self._decode_bytes(
            payload.get("data", ""),
            payload.get("data_encoding", "base64"),
        )
        accounts = [
            AccountMeta(
                Pubkey.from_string(account["pubkey"]),
                bool(account.get("is_signer", False)),
                bool(account.get("is_writable", False)),
            )
            for account in payload.get("accounts", [])
        ]
        return Instruction(Pubkey.from_string(program_id), data, accounts)

    def _required_signers(self, tx_bytes: bytes) -> list[str]:
        versioned = VersionedTransaction.from_bytes(tx_bytes)
        message = versioned.message
        count = message.header.num_required_signatures
        return [str(key) for key in list(message.account_keys)[:count]]

    def _decode_bytes(self, raw: str, encoding: str) -> bytes:
        if encoding == "hex":
            return bytes.fromhex(raw)
        if encoding == "base64":
            return base64.b64decode(raw)
        raise ValueError(f"Unsupported transaction encoding: {encoding}")
