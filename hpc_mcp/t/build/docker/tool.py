import hpc_mcp.t.build.docker.prompts as prompts
from hpc_mcp.logger import logger
import hpc_mcp.utils as utils
from hpc_mcp.result import Result
import shutil
import re
import os
import shutil
import tempfile
import subprocess
import shlex

from rich import print


def check_docker():
    """
    Setup ensures we have docker or podman installed.
    """
    docker = shutil.which("docker")
    if not docker:
        docker = shutil.which("podman")
    if not docker:
        raise ValueError("docker (or podman) not present on the system.")
    return docker


def docker_run_container(uri: str, command: str, as_json: bool = True):
    """
    Run a docker container. Accepts an optional unique resource identifier (URI).

    uri: the unique resource identifier.
    command: string to run (will be shlex split)
    """
    docker = check_docker()
    # Prepare command to push (docker or podman)
    command = [docker, "run", "-it", uri] + shlex.split(command)
    logger.info(f"Running {command}...")
    p = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if as_json:
        return Result(p).to_json()
    return Result(p).render()


def docker_push_container(uri: str, all_tags: bool = False, as_json: bool = True):
    """
    Push a docker container. Accepts an optional unique resource identifier (URI).

    uri: the unique resource identifier.
    all_tags: push to the registry all tags. The URI should NOT have an associated tag.
    """
    # Manual fix if the agent gets it wrong.
    if all_tags:
        uri = uri.split(":", 1)[0]

    # Prepare command to push (docker or podman)
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
    dockerfile: list[str], uri: str = "lammps", platforms: str = None, as_json: bool = True
):
    """
    Build a docker container. Accepts an optional unique resource identifier (URI).
    The build is always done in a protected temporary directory.

    dockerfile: the dockerfile to write and build
    uri: the unique resource identifier.
    platforms: Custom list of platforms (e.g., linux/amd64,linux/arm64) for a multi-stage build
    push: push to the registry. Requires that the docker agent is authenticated.
    load: load into a kubernetes in docker (kind) cluster.
    """
    # We pass as list because newlines in json... no go!
    dockerfile = "\n".join(dockerfile)

    # This ensures that we aren't given a code block, etc.
    pattern = "```(?:docker|dockerfile)?\n(.*?)```"
    match = re.search(pattern, dockerfile, re.DOTALL)
    if match:
        dockerfile = match.group(1).strip()
    else:
        dockerfile = utils.get_code_block(dockerfile, "dockerfile")

    # Not sure if this can happen, assume it can
    if not dockerfile:
        raise ValueError("No dockerfile content provided.")

    logger.custom(dockerfile, title="[green]Dockerfile Build[/green]", border_style="green")

    build_dir = tempfile.mkdtemp()
    print(f"[dim]Created temporary build context: {build_dir}[/dim]")

    # Write the Dockerfile to the temporary directory
    utils.write_file(dockerfile, os.path.join(build_dir, "Dockerfile"))

    prefix = [check_docker(), "build"]
    if platforms is not None:
        # Note that buildx for multiple platforms must be used with push
        prefix = ["docker", "buildx", "build", "--platform", platforms, "--push"]

    # Run the build process using the temporary directory as context
    p = subprocess.run(
        prefix + ["--network", "host", "-t", uri, "."],
        capture_output=True,
        text=True,
        cwd=build_dir,
        check=False,
    )
    # Clean up after we finish
    shutil.rmtree(build_dir, ignore_errors=True)

    # Streamline (filter) output and return result object
    p.stdout = filter_output(p.stdout)
    p.stderr = filter_output(p.stderr)
    if as_json:
        return Result(p).to_json()
    return Result(p).render()


def filter_output(output):
    """
    Remove standard lines (e.g., apt install stuff) that likely won't help but
    add many thousands of tokens... (in testing, from 272K down to 2k)
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
    output = "\n".join([x for x in output.split("\n") if not re.search(regex, x)])
    # Try to match lines that start with #<number>
    return "\n".join([x for x in output.split("\n") if not re.search(r"^#(\d)+ ", x)])


def kind_load(uri: str, load_type: str = "docker-image", as_json: bool = True):
    """
    Load a Docker URI into Kind (Kubernetes in Docker)

    uri: the unique resource identifier.
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
    if as_json:
        return Result(p).to_json()
    return Result(p).render()


def docker_build_persona_prompt(application: str, environment: str = "CPU") -> dict:
    """
    Generates agent instructions for creating a NEW Dockerfile.
    """
    # Specific rules for a fresh build
    build_rules = [
        "The Dockerfile content you generate must be complete and robust.",
        "The response should ONLY contain the complete Dockerfile.",
        "Use the available tools (files-write) to save the Dockerfile to disk.",
    ] + prompts.COMMON_INSTRUCTIONS

    # Construct the text from our template
    prompt_text = prompts.get_build_text(application, environment, build_rules)

    # Return MCP format
    return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt_text}}]}


def docker_fix_persona_prompt(error_message: str) -> dict:
    """
    Generates system instructions for retrying a failed build.
    """
    # 1. Define specific rules for fixing
    fix_rules = [
        "The response should only contain the complete, corrected Dockerfile content.",
        "Use succinct comments in the Dockerfile to explain build logic and changes.",
    ] + prompts.COMMON_INSTRUCTIONS

    prompt_text = prompts.get_retry_prompt(fix_rules, error_message)
    return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt_text}}]}
