"""X402Adapter — implements x402 protocol from Coinbase spec (no SDK dependency).

x402 flow (SVM/Solana exact scheme):
1. Client GETs resource → server returns 402 + PAYMENT-REQUIRED header
2. Client builds USDC SPL transfer tx, partially signs (as token authority)
3. Client retries with PAYMENT-SIGNATURE header containing base64 tx
4. Server co-signs (as fee payer), submits to chain, serves resource

Client never touches the chain. Server/facilitator is the fee payer and submitter.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx
from solana.rpc.async_api import AsyncClient as SolanaClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
from spl.token.instructions import (
    transfer_checked,
    TransferCheckedParams,
    get_associated_token_address,
)
from spl.token.constants import TOKEN_PROGRAM_ID

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)

# Solana compute budget program
COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
# Memo program for nonce
MEMO_PROGRAM = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


def _set_compute_unit_limit_ix(units: int) -> Instruction:
    """SetComputeUnitLimit instruction."""
    data = bytes([2]) + units.to_bytes(4, "little")
    return Instruction(COMPUTE_BUDGET_PROGRAM, data, [])


def _set_compute_unit_price_ix(micro_lamports: int) -> Instruction:
    """SetComputeUnitPrice instruction."""
    data = bytes([3]) + micro_lamports.to_bytes(8, "little")
    return Instruction(COMPUTE_BUDGET_PROGRAM, data, [])


def _memo_ix(msg: str, signer: Pubkey) -> Instruction:
    """Memo instruction with signer — serves as payment nonce."""
    return Instruction(
        MEMO_PROGRAM,
        msg.encode(),
        [AccountMeta(signer, is_signer=True, is_writable=False)],
    )


def parse_402_requirements(headers: dict[str, str]) -> dict:
    """Parse the PAYMENT-REQUIRED header from a 402 response."""
    raw = headers.get("payment-required", headers.get("PAYMENT-REQUIRED", ""))
    if not raw:
        raise ValueError("No PAYMENT-REQUIRED header in 402 response")
    decoded = json.loads(base64.b64decode(raw))
    if decoded.get("x402Version") == 2:
        return decoded["requirements"][0]
    # V1 fallback
    return decoded


async def build_payment_tx(
    keypair: Keypair,
    requirements: dict,
    rpc_url: str,
) -> bytes:
    """Build and partially sign a USDC transfer tx per x402 spec.

    The tx fee payer is the facilitator (from requirements.extra.feePayer).
    Client signs as token authority. Facilitator co-signs and submits later.
    """
    payer_address = requirements.get("extra", {}).get("feePayer", requirements["payTo"])
    fee_payer = Pubkey.from_string(payer_address)
    pay_to = Pubkey.from_string(requirements["payTo"])
    mint = Pubkey.from_string(requirements["asset"])
    amount = int(requirements["maxAmountRequired"])

    # Derive ATAs
    sender_ata = get_associated_token_address(keypair.pubkey(), mint)
    receiver_ata = get_associated_token_address(pay_to, mint)

    # Build instructions
    ixs = [
        _set_compute_unit_limit_ix(50_000),
        _set_compute_unit_price_ix(1000),
        transfer_checked(
            TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=sender_ata,
                mint=mint,
                dest=receiver_ata,
                owner=keypair.pubkey(),
                amount=amount,
                decimals=6,
                signers=[keypair.pubkey()],
            )
        ),
        _memo_ix(os.urandom(8).hex(), keypair.pubkey()),
    ]

    # Get recent blockhash
    async with SolanaClient(rpc_url) as rpc:
        bh_resp = await rpc.get_latest_blockhash()
        blockhash = bh_resp.value.blockhash

    # Build V0 message with fee payer = facilitator
    msg = MessageV0.try_compile(
        payer=fee_payer,
        instructions=ixs,
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    # Partially sign: fill in our signature, leave fee payer slot as default
    from solders.signature import Signature as SoldersSig
    from solders.message import to_bytes_versioned

    num_signers = msg.header.num_required_signatures
    signable = to_bytes_versioned(msg)

    # Build signature array: default for all, then fill in ours
    sigs = [SoldersSig.default()] * num_signers
    account_keys = list(msg.account_keys)
    for i, key in enumerate(account_keys[:num_signers]):
        if key == keypair.pubkey():
            sigs[i] = keypair.sign_message(signable)
            break

    tx = VersionedTransaction.populate(msg, sigs)
    return bytes(tx)


def encode_payment_header(tx_bytes: bytes, requirements: dict, resource: str) -> str:
    """Encode the PAYMENT-SIGNATURE header value."""
    payload = {
        "x402Version": 2,
        "payload": {
            "transaction": base64.b64encode(tx_bytes).decode(),
        },
        "accepted": {
            "scheme": requirements.get("scheme", "exact"),
            "network": requirements.get("network", ""),
        },
        "resource": resource,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


class X402Adapter(PaymentAdapter):
    """Handles x402 HTTP-native payment — builds and signs USDC transfer txs.

    When the HTTP client gets a 402, this adapter:
    1. Parses PAYMENT-REQUIRED header
    2. Builds a USDC SPL transfer tx
    3. Partially signs with the agent's keypair
    4. Returns the PAYMENT-SIGNATURE header for retry
    The server co-signs and submits to chain.
    """

    def __init__(
        self,
        keypair: Keypair | None = None,
        rpc_url: str = "http://127.0.0.1:8899",
    ) -> None:
        self._keypair = keypair
        self._rpc_url = rpc_url

    @property
    def id(self) -> str:
        return "x402"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        return challenge.type == "x402"

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        """Handle a 402 challenge: build tx, sign, return payment headers."""
        if self._keypair is None:
            raise RuntimeError("X402Adapter requires a keypair")

        requirements = challenge.extra.get("requirements", {})
        if not requirements:
            raise ValueError("No x402 requirements in challenge")

        tx_bytes = await build_payment_tx(
            self._keypair, requirements, self._rpc_url
        )

        payment_header = encode_payment_header(
            tx_bytes, requirements, challenge.extra.get("resource", "")
        )

        return PaymentReceipt(
            protocol="x402",
            amount=float(requirements.get("maxAmountRequired", 0)) / 1e6,
            currency="USDC",
            extra={
                "payment_header": payment_header,
                "network": requirements.get("network", ""),
            },
        )

    async def settle(self, session: PaymentSession) -> None:
        pass  # Server handles settlement

    async def refund(self, session: PaymentSession, reason: str) -> None:
        raise NotImplementedError("x402 refunds not supported")
