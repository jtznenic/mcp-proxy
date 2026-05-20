# /// script
# dependencies = ["mcp>=1.13.0"]
# ///

import asyncio
import os
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server


server = Server("mcp-proxy")


def load_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def split_names(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


class Config:
    def __init__(self) -> None:
        env_file = os.environ.get("ENV_FILE")
        if not env_file:
            raise RuntimeError("ENV_FILE is required")

        values = load_env_file(env_file)
        self.upstream_type = values.get("UPSTREAM_TYPE", "http").lower()
        self.upstream_url = values.get("UPSTREAM_URL", "")
        self.headers = {
            key.removeprefix("UPSTREAM_HEADER_"): value
            for key, value in values.items()
            if key.startswith("UPSTREAM_HEADER_")
        }
        self.allow_tools = split_names(values.get("ALLOW_TOOLS"))
        self.deny_tools = split_names(values.get("DENY_TOOLS"))

        if self.upstream_type != "http":
            raise RuntimeError("Only UPSTREAM_TYPE=http is supported")
        if not self.upstream_url:
            raise RuntimeError("UPSTREAM_URL is required")

    def tool_allowed(self, name: str) -> bool:
        if self.allow_tools:
            return name in self.allow_tools
        return name not in self.deny_tools


config = Config()


async def with_upstream(action: Any) -> Any:
    async with streamablehttp_client(config.upstream_url, headers=config.headers) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await action(session)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    async def action(session: ClientSession) -> list[types.Tool]:
        result = await session.list_tools()
        return [tool for tool in result.tools if config.tool_allowed(tool.name)]

    return await with_upstream(action)


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.ContentBlock]:
    if not config.tool_allowed(name):
        raise RuntimeError(f"Tool is not allowed: {name}")

    async def action(session: ClientSession) -> list[types.ContentBlock]:
        result = await session.call_tool(name, arguments or {})
        return result.content

    return await with_upstream(action)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp-proxy",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
