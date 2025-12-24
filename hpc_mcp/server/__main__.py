from mcp.server.fastmcp import FastMCP

from hpc_mcp.t.registry import TOOLS


def register_with(server_instance):
    """
    Register (mount) flux-mcp tools to a given MCP server instance.
    """
    # 1. Identify which kind of server it is (Optional robust check)
    if hasattr(server_instance, "add_tool"):
        # FastMCP pattern
        for func in TOOLS:
            server_instance.add_tool(func)

    elif hasattr(server_instance, "register_tool"):
        # Low-level Server pattern (requires more manual schema work)
        raise NotImplementedError("Please use FastMCP or wrapper")

    else:
        raise TypeError("Server instance must support .add_tool()")


def get_server():
    mcp = FastMCP(
        name="HPC MCP Gateway",
        instructions="This server provides tools for HPC.",
        website_url="https://github.com/converged-computing/hpc-mcp",
    )
    register_with(mcp)
    return mcp


def main():
    mcp = get_server()
    mcp.run()


if __name__ == "__main__":
    main()
