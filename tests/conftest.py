import json

import pytest
import pytest_asyncio
from fastmcp import Client


@pytest_asyncio.fixture
async def client():
    """
    Creates a Client connected to the HPC MCP tools.
    """
    server = "http://localhost:8089/mcp"
    async with Client(server) as c:
        yield c
