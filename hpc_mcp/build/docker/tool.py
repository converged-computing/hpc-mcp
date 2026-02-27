import hpc_mcp.build.docker.prompts as prompts
from hpc_mcp.logger import logger
import hpc_mcp.utils as utils
from hpc_mcp.result import Result
import shutil
import re
import os
import tempfile
import subprocess
import shlex
from typing import Annotated, Any, Dict, List, Optional, Union

from rich import print

ContainerURI = Annotated[
    str,
    "The unique resource identifier or image name/tag (e.g., 'lammps:latest' or 'user/repo:tag').",
]
ShellCommand = Annotated[str, "The shell command string to execute inside the container."]
JsonResultFlag = Annotated[
    bool,
    "If True, returns the result as a structured dictionary; if False, returns a rendered string.",
]
ToolOutput = Annotated[
    Union[str, Dict[str, Any]],
    "The structured output containing logs, metadata, and execution status.",
]
McpPromptResponse = Annotated[
    Dict[str, Any],
    "A dictionary containing a list of messages formatted for an LLM agent chat session.",
]


def check_docker() -> str:
    """
    Setup ensures we have docker or podman installed on the system path.

    Returns:
        str: The path to the discovered docker or podman binary.

    Raises:
        ValueError: If neither docker nor podman are present on the system.
    """
    docker = shutil.which("docker")
    if not docker:
        docker = shutil.which("podman")
    if not docker:
        raise ValueError("docker (or podman) not present on the system.")
    return docker


def filter_output(output: Optional[str]) -> str:
    """
    Remove standard noise lines (e.g., apt install progress) to reduce token usage.

    Args:
        output: The raw shell output string to be filtered.

    Returns:
        str: The filtered string containing only relevant logs.
    """
    skips = [
        "Get:",
        "Preparing to unpack",
        "Unpacking ",
        "Selecting previously ",
        "Setting up ",
        "update-alternatives",
        "Reading database ...",
        "Updating files",
    ]
    output = output or ""
    regex = "(%s)" % "|".join(skips)
    output_lines = [x for x in output.split("\n") if not re.search(regex, x)]
    output_lines = [x for x in output_lines if x.strip() not in ["\n", ""]]
    return "\n".join([x for x in output_lines if not re.search(r"^#(\d)+ ", x)])


def docker_run_container(
    uri: ContainerURI, command: ShellCommand, as_json: JsonResultFlag = True
) -> ToolOutput:
    """
    Executes a shell command inside a specified Docker container.

    Args:
        uri: The image name or URI to run.
        command: The command to execute (parsed via shlex).
        as_json: Return structured JSON if True.

    Returns:
        The command output, including stdout, stderr, and exit status.
    """
    docker = check_docker()
    command_list = [docker, "run", "-it", uri] + shlex.split(command)
    logger.info(f"Running {command_list}...")
    p = subprocess.run(
        command_list,
        capture_output=True,
        text=True,
        check=False,
    )
    if as_json:
        return Result(p).to_json()
    return Result(p).render()


def docker_push_container(
    uri: ContainerURI,
    all_tags: Annotated[bool, "Push all tags associated with this image repository."] = False,
    as_json: JsonResultFlag = True,
) -> ToolOutput:
    """
    Pushes a local container image to a remote registry.

    Args:
        uri: The image identifier to push.
        all_tags: If True, the tag is stripped from the URI to push the entire repo.
        as_json: Return structured JSON if True.

    Returns:
        The output of the push process from the Docker/Podman CLI.
    """
    if all_tags:
        uri = uri.split(":", 1)[0]

    command = [check_docker(), "push", uri]
    if all_tags:
        command.append("--all-tags")

    logger.info(f"Pushing to {uri}...")
    p = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if as_json:
        return Result(p).to_json()
    return Result(p).render()


def docker_build_container(
    dockerfile: Annotated[List[str], "List of strings representing the lines of the Dockerfile."],
    uri: ContainerURI = "lammps",
    platforms: Annotated[
        Optional[str], "Comma-separated target platforms (e.g., 'linux/amd64,linux/arm64')."
    ] = None,
    as_dict: JsonResultFlag = True,
) -> ToolOutput:
    """
    Builds a Docker container image from the provided Dockerfile lines.
    The build occurs in an isolated temporary directory.

    Args:
        dockerfile: The content of the Dockerfile as a list of lines.
        uri: The name/tag to assign to the resulting image.
        platforms: Optional platforms for cross-platform builds using buildx.
        as_dict: Return results as a dictionary if True.

    Returns:
        Filtered build logs and image metadata.
    """
    dockerfile_str = "\n".join(dockerfile)

    pattern = "```(?:docker|dockerfile)?\n(.*?)```"
    match = re.search(pattern, dockerfile_str, re.DOTALL)
    if match:
        dockerfile_str = match.group(1).strip()
    else:
        dockerfile_str = utils.get_code_block(dockerfile_str, "dockerfile")

    if not dockerfile_str:
        raise ValueError("No dockerfile content provided.")

    logger.custom(dockerfile_str, title="[green]Dockerfile Build[/green]", border_style="green")
    build_dir = tempfile.mkdtemp()
    print(f"[dim]Created temporary build context: {build_dir}[/dim]")
    utils.write_file(dockerfile_str, os.path.join(build_dir, "Dockerfile"))

    prefix = [check_docker(), "build"]
    if platforms is not None:
        prefix = ["docker", "buildx", "build", "--platform", platforms, "--push"]

    p = subprocess.run(
        prefix + ["--network", "host", "-t", uri, "."],
        capture_output=True,
        text=True,
        cwd=build_dir,
        check=False,
    )
    shutil.rmtree(build_dir, ignore_errors=True)

    p.stdout = filter_output(p.stdout)
    p.stderr = filter_output(p.stderr)
    if as_dict:
        return Result(p).to_dict()
    return Result(p).render()


def kind_load(
    uri: ContainerURI,
    load_type: Annotated[
        str, "The kind load subcommand (e.g., 'docker-image' or 'archive')."
    ] = "docker-image",
    as_dict: JsonResultFlag = True,
) -> ToolOutput:
    """
    Loads a local Docker image into a running Kind (Kubernetes in Docker) cluster.

    Args:
        uri: The image name and tag.
        load_type: The source type for the load operation.
        as_dict: Return results as a dictionary if True.

    Returns:
        Results from the Kind CLI utility.
    """
    kind = shutil.which("kind")
    if not kind:
        return logger.failure("Kind is not installed on the system.")

    logger.info("Loading into kind...")
    p = subprocess.run(
        [kind, "load", load_type, uri],
        capture_output=True,
        text=True,
        check=False,
    )
    if as_dict:
        return Result(p).to_dict()
    return Result(p).render()


def docker_build_persona_prompt(
    application: Annotated[str, "The name or description of the application to containerize."],
    environment: Annotated[
        str, "The target hardware/runtime (e.g., 'CPU', 'GPU', 'CUDA')."
    ] = "CPU",
) -> McpPromptResponse:
    """
    Generates tailored agent instructions for creating a NEW Dockerfile.

    Args:
        application: The software intended for containerization.
        environment: The target runtime constraints.

    Returns:
        An MCP formatted message payload for the agent.
    """
    build_rules = [
        "The Dockerfile content you generate must be complete and robust.",
        "The response should ONLY contain the complete Dockerfile.",
        "Use the available tools (files-write) to save the Dockerfile to disk.",
    ] + prompts.COMMON_INSTRUCTIONS

    prompt_text = prompts.get_build_text(application, environment, build_rules)
    return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt_text}}]}


def docker_fix_persona_prompt(
    error_message: Annotated[str, "The raw error logs from a failed build attempt."],
) -> McpPromptResponse:
    """
    Generates instructions for an agent to diagnose and fix a failed Docker build.

    Args:
        error_message: The diagnostic logs from the previous failure.

    Returns:
        An MCP formatted message payload for the agent.
    """
    fix_rules = [
        "The response should only contain the complete, corrected Dockerfile content.",
        "Use succinct comments in the Dockerfile to explain build logic and changes.",
    ] + prompts.COMMON_INSTRUCTIONS

    prompt_text = prompts.get_retry_prompt(fix_rules, error_message)
    return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt_text}}]}
