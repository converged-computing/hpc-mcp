import json
from typing import Annotated, Any, Dict, List

# Define custom type for MCP clarity
AgentPromptResponse = Annotated[
    Dict[str, Any],
    "A dictionary containing a list of messages formatted for an LLM agent chat session.",
]


def spack_software_request_persona(
    goal: Annotated[
        str,
        "The user's goal or software requirement (e.g., 'I need a chemistry simulation package')",
    ],
) -> AgentPromptResponse:
    """
    Generates a specialized prompt to guide an agent through the lifecycle of
    software discovery and installation using Spack.

    The resulting prompt encourages a logical workflow:
    1. Search for package names (spack_list)
    2. Check installed status (spack_find)
    3. Analyze variants/metadata (spack_info)
    4. Solve dependencies (spack_spec)
    5. Execute build (spack_install)
    """

    instruction = (
        "You are an HPC Software Engineer and Spack Expert. "
        "Your goal is to satisfy the user's software request using the Spack package manager.\n\n"
        "### STRATEGY\n"
        "1. **Discovery**: Use 'spack_list' to find package names matching the user's keywords.\n"
        "2. **Inventory**: Use 'spack_find' to see if a version is already installed.\n"
        "3. **Inspection**: Use 'spack_info' to understand available variants and versions.\n"
        "4. **Resolution**: Use 'spack_spec' to verify dependencies and the concrete build plan.\n"
        "5. **Installation**: If needed, use 'spack_install' with the specific variants requested.\n\n"
        f"### USER GOAL\n{goal}\n\n"
        "Please begin by searching for relevant packages."
    )

    return {"messages": [{"role": "user", "content": {"type": "text", "text": instruction}}]}
