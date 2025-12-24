__version__ = "0.0.0"
AUTHOR = "Vanessa Sochat"
AUTHOR_EMAIL = "vsoch@users.noreply.github.com"
NAME = "hpc-mcp"
PACKAGE_URL = "https://github.com/converged-computing/hpc-mcp"
KEYWORDS = "mcp, model context protocol, high performance computing, hpc, docker, build, workloads"
DESCRIPTION = "Agentic MCP tools for HPC"
LICENSE = "LICENSE"


################################################################################
# TODO vsoch: refactor this to use newer pyproject stuff.

INSTALL_REQUIRES = (
    ("mcp", {"min_version": None}),
    ("fastmcp", {"min_version": None}),
    ("rich", {"min_version": None}),
    ("fastapi", {"min_version": None}),
    # For Flux
    ("pyyaml", {"min_version": None}),
    ("ply", {"min_version": None}),
)

TESTS_REQUIRES = (
    ("pytest", {"min_version": "4.6.2"}),
    ("pytest-asyncio", {"min_version": None}),
)
INSTALL_REQUIRES_ALL = INSTALL_REQUIRES + TESTS_REQUIRES
