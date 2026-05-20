# /// script
# dependencies = ["mcp>=1.13.0"]
# ///

import asyncio
import os
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
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


def split_args(value: str | None) -> list[str]:
    if not value:
        return []
    return shlex.split(value, posix=False)


def same_path(left: str, right: str) -> bool:
    return Path(left.strip('"\'')).expanduser().resolve() == Path(right.strip('"\'')).expanduser().resolve()


def stdio_points_to_current_proxy(command: str, args: list[str]) -> bool:
    current_script = str(Path(__file__).resolve())
    return any(same_path(token, current_script) for token in [command, *args])


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
        self.upstream_command = values.get("UPSTREAM_COMMAND", "")
        self.upstream_args = split_args(values.get("UPSTREAM_ARGS"))
        self.upstream_env = {
            key.removeprefix("UPSTREAM_ENV_"): value
            for key, value in values.items()
            if key.startswith("UPSTREAM_ENV_")
        }
        self.allow_tools = split_names(values.get("ALLOW_TOOLS"))
        self.deny_tools = split_names(values.get("DENY_TOOLS"))

        if self.upstream_type not in {"http", "sse", "stdio"}:
            raise RuntimeError("UPSTREAM_TYPE must be one of: http, sse, stdio")
        if self.upstream_type in {"http", "sse"} and not self.upstream_url:
            raise RuntimeError("UPSTREAM_URL is required")
        if self.upstream_type == "stdio" and not self.upstream_command:
            raise RuntimeError("UPSTREAM_COMMAND is required")
        if self.upstream_type == "stdio" and stdio_points_to_current_proxy(
            self.upstream_command, self.upstream_args
        ):
            raise RuntimeError("stdio upstream cannot point back to this proxy script")

    def tool_allowed(self, name: str) -> bool:
        if self.allow_tools:
            return name in self.allow_tools
        return name not in self.deny_tools


config = Config()


@asynccontextmanager
async def upstream_session() -> AsyncIterator[ClientSession]:
    if config.upstream_type == "http":
        async with streamablehttp_client(config.upstream_url, headers=config.headers) as streams:
            read_stream, write_stream, _ = streams
            async with ClientSession(read_stream, write_stream) as session:
                yield session
    elif config.upstream_type == "sse":
        async with sse_client(config.upstream_url, headers=config.headers) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                yield session
    else:
        server_params = StdioServerParameters(
            command=config.upstream_command,
            args=config.upstream_args,
            env=config.upstream_env or None,
        )
        async with stdio_client(server_params) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                yield session


async def with_upstream(action: Any) -> Any:
    async with upstream_session() as session:
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
