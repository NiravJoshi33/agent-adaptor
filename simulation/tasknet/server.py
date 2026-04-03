"""Simulated Task Marketplace — mimics an AGICitizens-like platform.

Provides:
- Agent registration (with wallet-signed challenge-response)
- Task posting (by "requesters")
- Bidding, acceptance, delivery, and verification

The agent adapter interacts with this like any real platform — via HTTP.

Run: uvicorn simulation.tasknet.server:app --port 8002
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="TaskNet — Agent Task Marketplace",
    description="A marketplace where AI agents discover tasks, bid on them, and deliver results.",
    version="1.0.0",
)

# ── In-memory state ────────────────────────────────────────────────────

agents: dict[str, dict] = {}  # agent_id → agent info
api_keys: dict[str, str] = {}  # api_key → agent_id
tasks: dict[str, dict] = {}  # task_id → task
bids: dict[str, list[dict]] = {}  # task_id → [bids]
challenges: dict[str, str] = {}  # wallet_address → challenge nonce

# ── Models ─────────────────────────────────────────────────────────────


class ChallengeRequest(BaseModel):
    wallet_address: str


class ChallengeResponse(BaseModel):
    challenge: str
    message: str = "Sign this challenge with your wallet to register."


class RegisterRequest(BaseModel):
    wallet_address: str
    signature: str = Field(description="Hex-encoded signature of the challenge")
    name: str = Field(description="Agent display name")
    capabilities: list[str] = Field(description="List of capability names the agent offers")


class RegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    message: str


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str
    required_capability: str
    budget: float
    currency: str
    status: str
    requester: str
    input_data: dict[str, Any]
    result: dict[str, Any] | None = None


class BidRequest(BaseModel):
    price: float
    estimated_time_seconds: int = 30


class BidResponse(BaseModel):
    bid_id: str
    status: str
    message: str


class DeliverRequest(BaseModel):
    output: dict[str, Any]


class DeliverResponse(BaseModel):
    status: str
    message: str
    payment_amount: float = 0.0


# ── Platform docs endpoint ─────────────────────────────────────────────


@app.get("/docs.md", operation_id="get_platform_docs")
async def get_platform_docs() -> dict:
    """Returns platform documentation for agents — how to register, find tasks, bid, and deliver."""
    return {
        "platform": "TaskNet",
        "version": "1.0",
        "registration_flow": {
            "step_1": "POST /agents/challenge with your wallet_address to get a challenge nonce",
            "step_2": "Sign the challenge with your wallet",
            "step_3": "POST /agents/register with wallet_address, signature, name, and capabilities",
            "step_4": "You receive an agent_id and api_key. Store the api_key securely.",
        },
        "task_flow": {
            "step_1": "GET /tasks?status=open to find available tasks",
            "step_2": "POST /tasks/{task_id}/bid with your price",
            "step_3": "GET /tasks/{task_id} to check if your bid was accepted",
            "step_4": "Execute the task using your capabilities",
            "step_5": "POST /tasks/{task_id}/deliver with the output",
        },
        "authentication": "Include header: X-API-Key: <your_api_key>",
        "capabilities_matching": "Tasks specify a required_capability. Only bid on tasks matching your capabilities.",
    }


# ── Agent registration ─────────────────────────────────────────────────


@app.post(
    "/agents/challenge",
    response_model=ChallengeResponse,
    operation_id="request_challenge",
    summary="Request a registration challenge for wallet-based auth",
)
async def request_challenge(req: ChallengeRequest) -> ChallengeResponse:
    nonce = secrets.token_hex(16)
    challenge_msg = f"TaskNet-register:{nonce}"
    challenges[req.wallet_address] = challenge_msg
    return ChallengeResponse(challenge=challenge_msg)


@app.post(
    "/agents/register",
    response_model=RegisterResponse,
    operation_id="register_agent",
    summary="Register an agent with wallet signature verification",
)
async def register_agent(req: RegisterRequest) -> RegisterResponse:
    # In a real platform, we'd verify the signature against the wallet address.
    # For simulation, we just check a challenge was requested.
    if req.wallet_address not in challenges:
        raise HTTPException(400, "No challenge found. Request a challenge first.")

    # Accept registration
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    api_key = f"tsk_{secrets.token_hex(24)}"

    agents[agent_id] = {
        "id": agent_id,
        "wallet_address": req.wallet_address,
        "name": req.name,
        "capabilities": req.capabilities,
        "registered_at": time.time(),
    }
    api_keys[api_key] = agent_id
    del challenges[req.wallet_address]

    return RegisterResponse(
        agent_id=agent_id,
        api_key=api_key,
        message=f"Welcome {req.name}! Store your api_key securely.",
    )


# ── Auth helper ────────────────────────────────────────────────────────


def _auth(api_key: str | None) -> str:
    if not api_key or api_key not in api_keys:
        raise HTTPException(401, "Invalid or missing X-API-Key header")
    return api_keys[api_key]


# ── Tasks ──────────────────────────────────────────────────────────────


@app.get(
    "/tasks",
    response_model=list[TaskResponse],
    operation_id="list_tasks",
    summary="List tasks, optionally filtered by status",
)
async def list_tasks(
    status: str = "open", x_api_key: str | None = Header(None)
) -> list[TaskResponse]:
    _auth(x_api_key)
    return [
        TaskResponse(**t)
        for t in tasks.values()
        if t["status"] == status
    ]


@app.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    operation_id="get_task",
    summary="Get details of a specific task",
)
async def get_task(task_id: str, x_api_key: str | None = Header(None)) -> TaskResponse:
    _auth(x_api_key)
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    return TaskResponse(**tasks[task_id])


@app.post(
    "/tasks/{task_id}/bid",
    response_model=BidResponse,
    operation_id="bid_on_task",
    summary="Submit a bid on an open task",
)
async def bid_on_task(
    task_id: str, req: BidRequest, x_api_key: str | None = Header(None)
) -> BidResponse:
    agent_id = _auth(x_api_key)
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    task = tasks[task_id]
    if task["status"] != "open":
        raise HTTPException(400, f"Task is {task['status']}, not open")
    if req.price > task["budget"]:
        raise HTTPException(400, f"Bid ${req.price} exceeds budget ${task['budget']}")

    bid_id = f"bid_{uuid.uuid4().hex[:8]}"
    if task_id not in bids:
        bids[task_id] = []
    bids[task_id].append({
        "bid_id": bid_id,
        "agent_id": agent_id,
        "price": req.price,
        "estimated_time_seconds": req.estimated_time_seconds,
    })

    # Auto-accept first valid bid (simplification for demo)
    task["status"] = "in_progress"
    task["assigned_agent"] = agent_id
    task["accepted_bid"] = bid_id
    task["accepted_price"] = req.price

    return BidResponse(
        bid_id=bid_id,
        status="accepted",
        message=f"Bid accepted! Execute the task and deliver results.",
    )


@app.post(
    "/tasks/{task_id}/deliver",
    response_model=DeliverResponse,
    operation_id="deliver_task",
    summary="Deliver results for an assigned task",
)
async def deliver_task(
    task_id: str, req: DeliverRequest, x_api_key: str | None = Header(None)
) -> DeliverResponse:
    agent_id = _auth(x_api_key)
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    task = tasks[task_id]
    if task["status"] != "in_progress":
        raise HTTPException(400, f"Task is {task['status']}, expected in_progress")
    if task.get("assigned_agent") != agent_id:
        raise HTTPException(403, "You are not assigned to this task")

    # Accept delivery (auto-verify for demo)
    task["status"] = "completed"
    task["result"] = req.output
    task["completed_at"] = time.time()

    return DeliverResponse(
        status="completed",
        message="Delivery accepted and verified. Payment settled.",
        payment_amount=task.get("accepted_price", 0),
    )


# ── Requester endpoints (for simulation setup) ────────────────────────


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    required_capability: str
    budget: float
    currency: str = "USDC"
    input_data: dict[str, Any] = Field(default_factory=dict)


@app.post(
    "/requester/tasks",
    response_model=TaskResponse,
    operation_id="create_task",
    summary="[Requester] Create a new task for agents to bid on",
)
async def create_task(req: CreateTaskRequest) -> TaskResponse:
    """Used by requesters to post work. No auth for demo simplicity."""
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task = {
        "id": task_id,
        "title": req.title,
        "description": req.description,
        "required_capability": req.required_capability,
        "budget": req.budget,
        "currency": req.currency,
        "status": "open",
        "requester": "demo_requester",
        "input_data": req.input_data,
        "result": None,
    }
    tasks[task_id] = task
    return TaskResponse(**task)
