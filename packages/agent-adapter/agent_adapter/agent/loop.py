"""Embedded agent loop — the LLM brain that drives the adapter.

Uses OpenAI-compatible API (works with OpenRouter, OpenAI, local models).
Runs a tool-use conversation loop: plan → call tools → observe → repeat.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from agent_adapter.tools.definitions import build_tool_list
from agent_adapter.tools.handlers import ToolHandlers
from agent_adapter_contracts.types import ToolDefinition

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """\
You are an autonomous economic agent running inside the Agent Adapter Runtime.
Your job is to discover work on platforms, bid on tasks matching your capabilities,
execute them, deliver results, and manage payments — all autonomously.

## Your tools
- status__whoami: Start every planning loop here. Understand your current state.
- net__http_request: Interact with any platform API (register, bid, deliver, poll).
- net__fetch_spec: Fetch and parse OpenAPI specs to understand platform capabilities.
- secrets__store / secrets__retrieve / secrets__delete: Manage credentials. ALWAYS store API keys immediately upon receiving them.
- state__set / state__get / state__list: Persist operational data across restarts.
- wallet__get_address / wallet__get_balance / wallet__sign_message: Wallet operations for identity and payments.
- cap__*: Execute your capabilities against the target service.

## Rules
1. Always call status__whoami first to understand your current state.
2. Store credentials immediately with secrets__store — never lose an API key.
3. Match tasks to your enabled, priced capabilities only.
4. Never bid below your configured price floor.
5. Be concise in platform communications.
"""


class AgentLoop:
    """Single-turn or continuous agent loop using OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
        base_url: str = "https://openrouter.ai/api/v1",
        handlers: ToolHandlers | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        custom_prompt: str = "",
        max_tool_rounds: int = 20,
        extra_tools: list[ToolDefinition] | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._handlers = handlers
        self._max_tool_rounds = max_tool_rounds
        self._extra_tools = extra_tools or []

        prompt = system_prompt
        if custom_prompt:
            prompt += "\n\n## Provider Instructions\n" + custom_prompt
        self._system_prompt = prompt

    async def run_once(self, user_message: str = "Begin your planning loop.") -> str:
        """Run a single agent turn: plan → tool calls → observe → repeat until done.

        Returns the agent's final text response.
        """
        tools = build_tool_list(extra_tools=self._extra_tools)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        for round_num in range(self._max_tool_rounds):
            logger.info("Agent round %d, sending %d messages", round_num, len(messages))

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            choice = response.choices[0]
            message = choice.message

            # Add assistant message to conversation
            messages.append(message.model_dump(exclude_none=True))

            # If no tool calls, agent is done — return text
            if not message.tool_calls:
                logger.info("Agent finished after %d rounds", round_num + 1)
                return message.content or ""

            # Execute each tool call
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                logger.info("Tool call: %s(%s)", fn_name, json.dumps(fn_args)[:200])

                if self._handlers:
                    result = await self._handlers.dispatch(fn_name, fn_args)
                else:
                    result = json.dumps({"error": "No tool handlers configured"})

                logger.info("Tool result: %s", result[:200])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        return "Agent reached maximum tool rounds without completing."
