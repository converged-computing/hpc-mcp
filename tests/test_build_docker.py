import json
import shutil

import pytest

# Check availability of docker/podman to skip integration tests if missing
HAS_DOCKER = shutil.which("docker") is not None or shutil.which("podman") is not None


@pytest.mark.asyncio
async def test_docker_tool_list(client):
    """
    Verify Docker tools are registered.
    """
    tools = await client.list_tools()
    tool_names = [t.name for t in tools]

    expected_tools = [
        "docker_build_container",
        "docker_run_container",
        "docker_push_container",
        "docker_build_persona_prompt",
        "docker_fix_persona_prompt",
    ]

    for tool in expected_tools:
        assert tool in tool_names


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_DOCKER, reason="Docker or Podman not found on system")
async def test_docker_build_simple(client):
    """
    Test building a container from a simple list of strings.
    """
    dockerfile_content = ["FROM alpine:latest", "RUN echo 'hello world' > /test_file"]
    test_tag = "hpc-mcp-test:latest"
    result = await client.call_tool(
        "docker_build_container", {"dockerfile": dockerfile_content, "uri": test_tag}
    )

    # Result(p).render() returns a JSON string
    data = json.loads(result.content[0].text)
    assert data.get("returncode") == 0


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_DOCKER, reason="Docker or Podman not found on system")
async def test_docker_run_container(client):
    """
    Test running a container and capturing output.
    """
    # We use alpine because it is small and likely cached
    result = await client.call_tool(
        "docker_run_container", {"uri": "alpine:latest", "command": "echo 'mcp execution test'"}
    )

    data = json.loads(result.content[0].text)
    assert data.get("returncode") == 0
    assert "mcp execution test" in data.get("stdout", "")


@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="Let's not push anything")
@pytest.mark.skipif(not HAS_DOCKER, reason="Docker or Podman not found on system")
async def test_docker_push_structure(client):
    """
    Test the push command structure.
    Note: This will likely fail (exit code != 0) because we aren't authenticated
    to a real registry, but we verify the tool executes the subprocess logic.
    """
    # Use a local tag that definitely shouldn't push to a real registry
    result = await client.call_tool(
        "docker_push_container", {"uri": "localhost:5000/test-image:latest"}
    )

    data = json.loads(result.content[0].text)

    # We expect the tool to run, even if the docker command returns an error
    assert "exit_code" in data
    assert "stdout" in data
    assert "stderr" in data


@pytest.mark.asyncio
async def test_docker_build_persona_prompt(client):
    """Test the prompt generation for creating new Dockerfiles."""
    result = await client.call_tool(
        "docker_build_persona_prompt", {"application": "LAMMPS", "environment": "GPU"}
    )

    # The function returns a dict, FastMCP serializes it to JSON string
    data = json.loads(result.content[0].text)

    assert "messages" in data
    assert len(data["messages"]) > 0
    content = data["messages"][0]["content"]["text"]

    # Check that inputs were injected into the template
    assert "LAMMPS" in content
    assert "GPU" in content
    assert "The Dockerfile content you generate must be complete" in content


@pytest.mark.asyncio
async def test_docker_fix_persona_prompt(client):
    """Test the prompt generation for fixing build errors."""
    error_msg = "Package 'gcc' not found"

    result = await client.call_tool("docker_fix_persona_prompt", {"error_message": error_msg})

    data = json.loads(result.content[0].text)

    assert "messages" in data
    content = data["messages"][0]["content"]["text"]

    # Check if error message was injected
    assert error_msg in content
    # Check for specific fix instructions
    assert "succinct comments" in content
