from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwencoder_cua.integrations.mcp import MCPServerConfig, MCPToolSession


def test_server_config_requires_exactly_one_transport():
    with pytest.raises(ValueError, match="exactly one"):
        MCPServerConfig(name="invalid")
    with pytest.raises(ValueError, match="exactly one"):
        MCPServerConfig(name="invalid", url="http://localhost:8000/mcp", command="python")


def test_server_config_restricts_insecure_remote_http():
    with pytest.raises(ValueError, match="HTTPS"):
        MCPServerConfig(name="remote", url="http://example.com/mcp")


def test_server_config_allows_local_http_and_https():
    assert MCPServerConfig(name="local", url="http://127.0.0.1:8000/mcp").url
    assert MCPServerConfig(name="remote", url="https://example.com/mcp").url


def test_tool_invocation_requires_explicit_allow_list():
    import asyncio

    config = MCPServerConfig(name="paint", url="http://localhost:8000/mcp")
    session = MCPToolSession(config)
    with pytest.raises(PermissionError, match="not allow-listed"):
        asyncio.run(session.call_tool("draw_circle", {"radius": 10}))


class FakeClient:
    def __init__(self):
        self.calls = []
        self.pages = [
            SimpleNamespace(
                tools=[SimpleNamespace(
                    name="draw_circle", title="Draw circle", description="Draw a circle",
                    input_schema={"type": "object", "properties": {"radius": {"type": "integer"}}},
                )],
                next_cursor="page-2",
            ),
            SimpleNamespace(tools=[SimpleNamespace(
                name="save_image", title=None, description="Save image",
                input_schema={"type": "object"},
            )], next_cursor=None),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def list_tools(self, cursor=None):
        self.calls.append(("list", cursor))
        return self.pages.pop(0)

    async def call_tool(self, name, arguments):
        self.calls.append(("call", name, arguments))
        return SimpleNamespace(
            is_error=False,
            content=[SimpleNamespace(type="text", text="Circle drawn")],
            structured_content={"success": True},
        )


def test_session_discovers_paginated_tools_and_calls_allow_listed_tool():
    import asyncio

    async def exercise():
        fake = FakeClient()
        config = MCPServerConfig(
            name="paint",
            url="http://localhost:8000/mcp",
            allowed_tools=frozenset({"draw_circle"}),
        )
        async with MCPToolSession(config, client_factory=lambda _config: fake) as session:
            tools = await session.list_tools()
            result = await session.call_tool("draw_circle", {"radius": 42})
        return fake, tools, result

    fake, tools, result = asyncio.run(exercise())
    assert [tool["name"] for tool in tools] == ["draw_circle", "save_image"]
    assert tools[0]["input_schema"]["properties"]["radius"]["type"] == "integer"
    assert result["is_error"] is False
    assert result["structured_content"] == {"success": True}
    assert fake.calls == [
        ("list", None),
        ("list", "page-2"),
        ("call", "draw_circle", {"radius": 42}),
    ]


def test_session_rejects_non_allow_listed_tool():
    import asyncio

    async def exercise():
        fake = FakeClient()
        config = MCPServerConfig(
            name="paint", url="http://localhost:8000/mcp", allowed_tools=frozenset({"draw_circle"})
        )
        async with MCPToolSession(config, client_factory=lambda _config: fake) as session:
            with pytest.raises(PermissionError, match="not allow-listed"):
                await session.call_tool("delete_all", {})
        return fake

    fake = asyncio.run(exercise())
    assert not [call for call in fake.calls if call[0] == "call"]
