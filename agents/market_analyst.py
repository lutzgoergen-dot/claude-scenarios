"""
Managed agents example for creditport.

Demonstrates the Agent SDK's subagent pattern with two specialist agents:
  - data-loader: reads market data files and summarises them
  - scenario-analyst: interprets scenario results and flags risks

Run:
    python agents/market_analyst.py
"""

import anyio
from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    query,
)

DATA_DIR = "data/examples"


async def main() -> None:
    async for message in query(
        prompt=(
            f"Use the data-loader agent to read any CSV files in '{DATA_DIR}' and "
            "summarise the market data snapshot (indices, spreads, vols). "
            "Then use the scenario-analyst agent to describe what a +20bp parallel "
            "spread shift would likely mean for a long-payer portfolio."
        ),
        options=ClaudeAgentOptions(
            cwd="/home/user/claude-scenarios",
            allowed_tools=["Read", "Glob", "Grep", "Agent"],
            permission_mode="acceptEdits",
            agents={
                "data-loader": AgentDefinition(
                    description=(
                        "Reads market data files (CSV/Excel) and returns a structured "
                        "summary: indices present, spread levels, vol surface shape."
                    ),
                    prompt=(
                        "You are a market data specialist for credit index options. "
                        "Read the files you are given and return a concise, structured "
                        "summary suitable for a quant analyst."
                    ),
                    tools=["Read", "Glob"],
                ),
                "scenario-analyst": AgentDefinition(
                    description=(
                        "Interprets credit scenario inputs and explains P&L / risk "
                        "implications in plain language for a given portfolio direction."
                    ),
                    prompt=(
                        "You are a credit derivatives risk analyst. "
                        "Given a scenario description and portfolio direction, explain "
                        "the likely P&L impact, key risks, and any hedging considerations. "
                        "Be concise and quantitatively precise where possible."
                    ),
                    tools=["Read"],
                ),
            },
        ),
    ):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            session_id = message.data.get("session_id", "unknown")
            print(f"Session: {session_id}\n")
        elif isinstance(message, ResultMessage):
            print(message.result)
            print(f"\n[stop_reason: {message.stop_reason}]")


if __name__ == "__main__":
    anyio.run(main)
