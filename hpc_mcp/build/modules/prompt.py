from typing import Annotated, Any, Dict, List

AgentPromptResponse = Annotated[
    Dict[str, Any],
    "A dictionary containing a list of messages formatted for an LLM agent chat session.",
]


def module_software_request_persona(
    goal: Annotated[
        str,
        "The user's goal or requested software (e.g., 'I need an MPI library compiled with GCC')",
    ],
) -> AgentPromptResponse:
    """
    Generates a specialized prompt to guide an agent through the lifecycle of
    environment module discovery and environment setup.

    The resulting prompt encourages a logical workflow:
    1. Search for available modules (module_avail)
    2. Inspect module details and environment changes (module_show)
    3. Generate the correct load string for execution (module_load_instruction)
    """

    instruction = (
        "You are an HPC Systems Expert specialized in Environment Modules (Lmod/Tcl). "
        "Your goal is to help the user configure their shell environment to use specific software.\n\n"
        "### STRATEGY\n"
        "1. **Discovery**: Use 'module_avail' to search for modules matching the user's software needs.\n"
        "2. **Inspection**: Use 'module_show' to see what environment variables (PATH, LD_LIBRARY_PATH) a module modifies.\n"
        "3. **Context**: Provide the user with the exact 'module load ...' command required to proceed.\n\n"
        f"### USER GOAL\n{goal}\n\n"
        "Please begin by searching for relevant modules using 'module_avail'."
    )

    return {"messages": [{"role": "user", "content": {"type": "text", "text": instruction}}]}
