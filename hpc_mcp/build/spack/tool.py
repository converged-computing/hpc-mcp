import json
import os
import time
import subprocess
import shutil
import logging
from typing import Annotated, Any, Dict, List, Optional, Union
from hpc_mcp.logger import logger

# Don't cache 'find' or 'spec' as these change with the system state.
SPACK_CACHE = {"list": None, "info": {}}
CACHE_TTL = 600  # 10 minutes

SpackQueryResult = Annotated[
    Dict[str, Any],
    "A structured result containing 'success' (bool), 'data' (list or dict), and 'error' (str or None).",
]

SpackActionResponse = Annotated[
    Dict[str, Any],
    "A response from an execution command containing 'success' (bool), 'output' (str), and 'exit_code' (int).",
]


def get_spack_bin() -> str:
    """Locates the spack executable."""
    path = shutil.which("spack")
    if path:
        return path
    root = os.environ.get("SPACK_ROOT")
    if root:
        return os.path.join(root, "bin", "spack")
    raise FileNotFoundError("Spack binary not found. Set SPACK_ROOT or add to PATH.")


def run_spack_cmd(args: List[str]) -> subprocess.CompletedProcess:
    """Executes a spack command and captures output."""
    return subprocess.run([get_spack_bin()] + args, capture_output=True, text=True, check=False)


def spack_list(
    query: Annotated[Optional[str], "Search string to filter available package names."] = None,
    use_cache: Annotated[bool, "Use cached results for the repository listing."] = True,
) -> SpackQueryResult:
    """
    Lists all available packages in the Spack repository.

    Args:
        query: Optional string to filter the full list of packages.
        use_cache: Whether to use the global cache for the full repo list.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the command ran.
            - 'data' (list): List of package names (strings).
            - 'error' (str|None): Error details if failed.
    """
    global SPACK_CACHE
    now = time.time()

    if use_cache and SPACK_CACHE["list"] and (now - SPACK_CACHE["list"]["ts"] < CACHE_TTL):
        packages = SPACK_CACHE["list"]["data"]
    else:
        result = run_spack_cmd(["list"])
        if result.returncode != 0:
            return {"success": False, "data": [], "error": result.stderr.strip()}
        packages = result.stdout.split()
        SPACK_CACHE["list"] = {"data": packages, "ts": now}

    if query:
        packages = [p for p in packages if query in p]

    return {"success": True, "data": packages, "error": None}


def spack_find(
    spec: Annotated[
        Optional[str], "Constraint to filter installed packages (e.g. 'zlib@1.2.11')."
    ] = None,
) -> SpackQueryResult:
    """
    Queries the list of currently installed packages on the system.
    This tool is never cached to ensure accuracy of current system state.

    Args:
        spec: Optional spack spec to filter the search results.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if command succeeded.
            - 'data' (list): List of installed package objects (via JSON).
            - 'error' (str|None): Error details.
    """
    args = ["find", "--json"]
    if spec:
        args.append(spec)

    result = run_spack_cmd(args)
    if result.returncode != 0:
        return {"success": False, "data": [], "error": result.stderr.strip()}

    try:
        data = json.loads(result.stdout)
        return {"success": True, "data": data, "error": None}
    except json.JSONDecodeError as e:
        return {"success": False, "data": [], "error": f"JSON Parse Error: {e}"}


def spack_info(
    package_name: Annotated[str, "The name of the package to inspect."],
) -> SpackQueryResult:
    """
    Retrieves detailed metadata about a package (variants, versions, dependencies).

    Args:
        package_name: The name of the package (e.g., 'lammps').

    Returns:
        A dictionary containing:
            - 'success' (bool): True if found.
            - 'data' (dict): Contains the 'raw_text' description of the package.
            - 'error' (str|None): Error if the package name is invalid.
    """
    global SPACK_CACHE
    now = time.time()

    if package_name in SPACK_CACHE["info"]:
        cached = SPACK_CACHE["info"][package_name]
        if now - cached["ts"] < CACHE_TTL:
            return {"success": True, "data": cached["data"], "error": None}

    result = run_spack_cmd(["info", package_name])
    if result.returncode != 0:
        return {"success": False, "data": {}, "error": result.stderr.strip()}

    data = {"raw_text": result.stdout.strip()}
    SPACK_CACHE["info"][package_name] = {"data": data, "ts": now}
    return {"success": True, "data": data, "error": None}


def spack_spec(
    spec: Annotated[str, "The spec to concretize (e.g., 'hdf5 +fortran %gcc')."],
) -> SpackQueryResult:
    """
    Concretizes a spec and returns the full dependency resolution plan.
    This tool is never cached.

    Args:
        spec: The spack spec string to evaluate.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if concretization succeeded.
            - 'data' (dict): The concretized dependency graph in JSON format.
            - 'error' (str|None): Resolution error if the spec is unsatisfiable.
    """
    result = run_spack_cmd(["spec", "--json", spec])
    if result.returncode != 0:
        return {"success": False, "data": {}, "error": result.stderr.strip()}

    try:
        data = json.loads(result.stdout)
        return {"success": True, "data": data, "error": None}
    except json.JSONDecodeError as e:
        return {"success": False, "data": {}, "error": f"Failed to parse JSON: {e}"}


def spack_install(
    spec: Annotated[str, "The full spec to build and install."],
    verbose: Annotated[bool, "Capture verbose build output."] = False,
) -> SpackActionResponse:
    """
    Initiates the build and installation of a Spack spec.
    Note: This can be a very high-latency operation.

    Args:
        spec: The spec string (e.g., 'zlib %gcc@11').
        verbose: Whether to include build logs in the response.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if installation finished successfully.
            - 'output' (str): Compilation output or error logs.
            - 'exit_code' (int): The process exit code.
    """
    args = ["install", "--no-checksum"]
    if verbose:
        args.append("-v")
    args.append(spec)

    logger.info(f"Spack Install initiated for spec: {spec}")
    result = run_spack_cmd(args)

    return {
        "success": result.returncode == 0,
        "output": result.stdout if result.returncode == 0 else result.stderr,
        "exit_code": result.returncode,
    }
