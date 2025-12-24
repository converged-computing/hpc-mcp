import os

from fastmcp import FastMCP

import hpc_mcp.version as version

from .middleware import TokenAuthMiddleware

mcp = FastMCP(
    name="Flux MCP Gateway",
    instructions="This server provides tools for Flux Framework.",
    website_url="https://github.com/converged-computing/flux-mcp",
    version=version.__version__,
    # Throw up if we accidentally define a tool with the same name
    on_duplicate_tools="error",
)

# Authentication - let's do simple BearerToken from environment for now
auth_token = os.environ.get("HPC_MCP_TOKEN")
auth = None
if auth_token:
    auth = TokenAuthMiddleware(auth_token)
    mcp.add_middleware(auth)


def init_mcp(exclude_tags=None, include_tags=None, mask_error_details=False):
    """
    Function to init app. Doesn't need to be called at start as long as called
    to update global context.
    """
    global mcp

    mcp.exclude_tags = set(exclude_tags or []) or None
    mcp.include_tags = set(include_tags or []) or None
    mcp.mask_error_details = mask_error_details
    return mcp
