"""FastAPI management API for local provider operations."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent_adapter.runtime import RuntimeContext


class CapabilityPricingRequest(BaseModel):
    model: str
    amount: float
    currency: str = "USDC"
    item_field: str = ""
    floor: float = 0.0
    ceiling: float = 0.0


def create_management_app(runtime: RuntimeContext) -> FastAPI:
    app = FastAPI(
        title="Agent Adapter Management API",
        version="0.1.0",
        docs_url="/manage/docs",
        openapi_url="/manage/openapi.json",
    )

    @app.get("/manage/status")
    async def get_status():
        return await runtime.whoami()

    @app.get("/manage/wallet")
    async def get_wallet():
        status = await runtime.whoami()
        return {
            "address": status["wallet"],
            "balances": status["balances"],
        }

    @app.get("/manage/capabilities")
    async def list_capabilities():
        return {"capabilities": await runtime.list_capabilities()}

    @app.post("/manage/capabilities/refresh")
    async def refresh_capabilities():
        return {"capabilities": await runtime.refresh_capabilities()}

    @app.put("/manage/capabilities/{name}/pricing")
    async def update_capability_pricing(name: str, request: CapabilityPricingRequest):
        try:
            return await runtime.set_capability_pricing(
                name,
                model=request.model,
                amount=request.amount,
                currency=request.currency,
                item_field=request.item_field,
                floor=request.floor,
                ceiling=request.ceiling,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {name}") from exc

    @app.post("/manage/capabilities/{name}/enable")
    async def enable_capability(name: str):
        try:
            return await runtime.set_capability_enabled(name, True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {name}") from exc

    @app.post("/manage/capabilities/{name}/disable")
    async def disable_capability(name: str):
        try:
            return await runtime.set_capability_enabled(name, False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {name}") from exc

    @app.get("/manage/jobs")
    async def list_jobs(limit: int = 20):
        return {"jobs": await runtime.list_jobs(limit)}

    @app.get("/manage/platforms")
    async def list_platforms():
        return {"platforms": await runtime.list_platforms()}

    @app.get("/manage/agent/decisions")
    async def list_decisions(limit: int = 50):
        return {"decisions": await runtime.list_decisions(limit)}

    @app.post("/manage/agent/pause")
    async def pause_agent():
        return await runtime.pause_agent()

    @app.post("/manage/agent/resume")
    async def resume_agent():
        return await runtime.resume_agent()

    return app
