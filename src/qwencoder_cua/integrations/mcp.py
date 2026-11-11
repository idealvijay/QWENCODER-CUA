"""Optional MCP client integration.

This module deliberately stays outside the desktop task planner and runner. It
provides an explicit client API for discovering and invoking tools exposed by
trusted MCP servers without changing QWENCODER's native CUA action contract.

Install the optional dependency with ``pip install 'qwencoder-cua[mcp]'``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class MCPServerConfig:
    """Connection settings for one trusted MCP server.

    Configure exactly one transport:
    - ``url`` for a Streamable HTTP endpoint.
    - ``command`` (and optional ``args`` / ``env``) for a local stdio process.

    Tool execution is disabled unless the requested tool is explicitly included
    in ``allowed_tools``. Discovery remains available without an allow-list.
    """

    name: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    allowed_tools: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("MCP server name must not be empty.")
        if (self.url is None) == (self.command is None):
            raise ValueError("Configure exactly one of url or command.")
        if self.url is not None:
            parsed = urlparse(self.url)
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in local_hosts
            ):
                raise ValueError(
                    "MCP HTTP endpoints must use HTTPS; HTTP is allowed only for localhost."
                )
            if not parsed.netloc:
                raise ValueError("MCP server URL must include a hostname.")
            if self.args or self.env:
                raise ValueError("args and env are only valid for stdio servers.")
        if self.command is not None and not self.command.strip():
            raise ValueError("MCP stdio command must not be empty.")
        if any(not item for item in self.args):
            raise ValueError("MCP stdio arguments must not contain empty values.")
        if any(not name for name in self.allowed_tools):
            raise ValueError("Allowed MCP tool names must not be empty.")


class MCPToolSession:
    """Connected session for listing and explicitly invoking MCP tools.

    The optional ``client_factory`` is intended for tests and embedding. Normal
    callers should omit it; the official MCP SDK is imported lazily only when a
    session is opened.
    """

    def __init__(
        self,
        config: MCPServerConfig,
        client_factory: Callable[[MCPServerConfig], Any] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._client_context: Any = None
        self._client: Any = None

    async def __aenter__(self) -> "MCPToolSession":
        if self._client_factory is not None:
            self._client_context = self._client_factory(self.config)
        else:
            try:
                from mcp import Client, StdioServerParameters
            except ImportError as exc:
                raise RuntimeError(
                    "MCP support is optional. Install it with: "
                    "python -m pip install 'qwencoder-cua[mcp]'"
                ) from exc

            if self.config.url is not None:
                target = self.config.url
            else:
                target = StdioServerParameters(
                    command=self.config.command,
                    args=list(self.config.args),
                    env=dict(self.config.env) or None,
                )
            self._client_context = Client(target)

        self._client = await self._client_context.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> Any:
        if self._client_context is None:
            return None
        try:
            return await self._client_context.__aexit__(exc_type, exc, traceback)
        finally:
            self._client = None
            self._client_context = None

    def _require_connected(self) -> Any:
        if self._client is None:
            raise RuntimeError("MCPToolSession must be used inside 'async with'.")
        return self._client

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover every tool exposed by the connected server."""
        client = self._require_connected()
        discovered: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = await client.list_tools(cursor=cursor)
            for tool in page.tools:
                discovered.append({
                    "name": tool.name,
                    "title": getattr(tool, "title", None),
                    "description": getattr(tool, "description", None),
                    "input_schema": tool.input_schema,
                })
            cursor = getattr(page, "next_cursor", None)
            if cursor is None:
                return discovered

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Invoke one allow-listed tool and return its content and error status."""
        if name not in self.config.allowed_tools:
            raise PermissionError(
                f"MCP tool {name!r} is not allow-listed for server "
                f"{self.config.name!r}. Add it to MCPServerConfig.allowed_tools "
                "after reviewing the server and tool schema."
            )
        client = self._require_connected()
        result = await client.call_tool(name, dict(arguments or {}))
        content: list[dict[str, Any]] = []
        for block in result.content:
            if hasattr(block, "model_dump"):
                content.append(block.model_dump(mode="json"))
            elif isinstance(block, dict):
                content.append(block)
            else:
                content.append({"type": type(block).__name__})

        return {
            "is_error": bool(result.is_error),
            "content": content,
            "structured_content": getattr(result, "structured_content", None),
        }
