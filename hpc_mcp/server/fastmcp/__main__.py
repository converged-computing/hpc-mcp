#!/usr/bin/env python3
from fastapi import FastAPI
from fastmcp.tools.tool import Tool

from hpc_mcp.t.registry import TOOLS

from .app import init_mcp


def register_with(server_instance):
    for func in TOOLS:
        tool_obj = Tool.from_function(func)
        server_instance.add_tool(tool_obj)
        print(f"   ✅ Registered: {func.__name__}")


def main():
    mcp = init_mcp()

    # Create ASGI app from MCP server
    mcp_app = mcp.http_app(path="/mcp")
    app = FastAPI(title="HPC MCP", lifespan=mcp_app.lifespan)

    # Dynamic Loading of Tools
    print(f"🔌 Registering tools... ")
    register_with(mcp)

    # Mount the MCP server. Note from V: we can use mount with antother FastMCP
    # mcp.run can also be replaced with mcp.run_async
    app.mount("/", mcp_app)

    # TODO customize transport if needed. This is just a demo, so likely not.
    try:
        mcp.run(transport="http", port=8089, host="0.0.0.0")
    except KeyboardInterrupt:
        print("🖥️  Shutting down...")


if __name__ == "__main__":
    main()
