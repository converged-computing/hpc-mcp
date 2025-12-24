# hpc-mcp

> 🌀 Agentic MCP tools for High Performance Computing

[![PyPI version](https://badge.fury.io/py/hpc-mcp.svg)](https://badge.fury.io/py/hpc-mcp)

![img/hpc-mcp.png](https://github.com/converged-computing/hpc-mpc/blob/main/img/hpc-mcp-small.png?raw=true)

## Related Projects

 - [flux-mcp](https://github.com/converged-computing/flux-mcp): MCP functions for Flux Framework.
 - [fractale-mcp](https://github.com/compspec/fractale-mcp): (fractale) MCP orchestration (agents, databases, ui interfaces).

## Usage

This is a library of MCP tools (functions, prompts, and resources) intended for converged computing and HPC use cases. A demo server is provided here, and largely functions are expected to be used a-la-carte as imports to other libraries. We welcome contributions of all functions types that are related to HPC, converged computing, and science. These MCP tools can be used via a standalone server, or combined with other tools.

### Server

We provide examples for fastmcp and a vanilla mcp (stdio) setup. Neither requirements are added to the install directly, so it's up to the user (you) to install. Tests are performed with fastmcp (TBA)

#### fastmcp

You will need fastapi and fastmcp installed.

```bash
# fastmcp
pip install fastmcp fastapi
```

To start the demo server:

```bash
# Vanilla MCP (with cli)
echo '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}}' | python3 -m hpc_mcp.server | jq

# Initialize and list tools
(echo '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "manual-test", "version": "1.0"}}}';
 echo '{"jsonrpc": "2.0", "method": "notifications/initialized"}';
 echo '{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}') | python3 -m hpc_mcp.server | jq

# FastMCP
python3 -m hpc_mcp.server.fastmcp
```

### Testing

I will add tools to git as I write tests for them. To test, start the fastmcp server in one terminal:

```bash
python3 -m hpc_mcp.server.fastmcp
```

In another terminal, run the test. You'll need to `pip install pytest pytest-asyncio`

```bash
pytest -xs tests/test_build_docker.py

# or
pytest -xs tests/test_*.py
```

## TODO

- Add annotated descriptions to all functions for LLM.

## License

DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
