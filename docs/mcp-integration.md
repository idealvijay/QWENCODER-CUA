# Optional MCP client integration

QWENCODER CUA can connect to external Model Context Protocol (MCP) servers to
discover their tools and invoke explicitly approved tools. This is an optional
integration; it does not replace or modify the desktop driver, task planner,
`TaskStep` schema, task runner, verification loop, or native action allow-list.

## Install

```bash
python -m pip install -e ".[mcp]"
```

The MCP SDK is optional. Standard QWENCODER CUA installation and native CUA
workflows do not require it.

## Connect to a local stdio server

```python
import asyncio

from qwencoder_cua.integrations.mcp import MCPServerConfig, MCPToolSession


async def main():
    server = MCPServerConfig(
        name="paint",
        command="python",
        args=("paint_server.py",),
        # Review the discovered schema before enabling an action.
        allowed_tools=frozenset({"draw_circle"}),
    )

    async with MCPToolSession(server) as session:
        tools = await session.list_tools()
        for tool in tools:
            print(tool["name"], tool["description"], tool["input_schema"])

        result = await session.call_tool("draw_circle", {"x": 500, "y": 300, "radius": 80})
        print(result)


asyncio.run(main())
```

The stdio command is launched as a subprocess by the MCP SDK and is shut down
when the session exits. Only pass commands and server packages that you trust.

## Connect to a Streamable HTTP server

```python
server = MCPServerConfig(
    name="paint-remote",
    url="https://mcp.example.com/mcp",
    allowed_tools=frozenset({"draw_circle"}),
)

async with MCPToolSession(server) as session:
    print(await session.list_tools())
```

Plain HTTP is accepted only for loopback endpoints (`localhost`, `127.0.0.1`,
`::1`). Use HTTPS for remote endpoints.

## Safety and architecture boundaries

- Tool discovery is read-only and does not enable tool execution.
- `call_tool` rejects every tool not named in `allowed_tools`.
- Review the MCP server and each tool's description and input schema before
  adding it to the allow-list. An MCP tool may read data or make changes outside
  the desktop session.
- Stdio servers run as local subprocesses. Use trusted commands and pass only
  the environment variables that the server needs.
- MCP tool calls are explicit application-level operations. They are **not**
  accepted as `TaskStep` actions and are not executed by `TaskRunner`.
- The existing CUA planner, action schema, native driver registry, policy checks,
  approval gates, and visual/accessibility verification remain unchanged.

This integration is a transport/client layer only. A future planner integration
would require a separate design review for tool selection, approval, argument
validation, execution budgets, and postcondition verification; it is intentionally
not part of this change.
