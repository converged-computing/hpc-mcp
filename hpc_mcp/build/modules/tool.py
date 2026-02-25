import json
import os
import subprocess
import time
from typing import Annotated, Any, Dict, List, Optional, Union
from hpc_mcp.logger import logger

MODULE_CACHE = {"avail": None, "show": {}}
CACHE_TTL = 300  # 5 minutes

ModuleQueryResult = Annotated[
    Dict[str, Any],
    "A structured result containing 'success' (bool), 'data' (list or dict), and 'error' (str or None).",
]


def run_module_cmd(args: str) -> subprocess.CompletedProcess:
    """Executes a module command via a login shell."""
    full_cmd = f"module {args}"
    return subprocess.run(
        ["/bin/bash", "-l", "-c", full_cmd], capture_output=True, text=True, check=False
    )


def module_avail(
    query: Annotated[
        Optional[str], "Search string to filter modules (e.g., 'gcc' or 'openmpi')."
    ] = None,
    use_cache: Annotated[bool, "If True, use the cached listing if available."] = True,
) -> ModuleQueryResult:
    """
    Lists available modules currently discoverable in the MODULEPATH.

    Args:
        query: Optional string to filter the module list.
        use_cache: Whether to return previously cached results to save time.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the command executed.
            - 'data' (list|dict): A list of available modules or a 'raw_text' field for non-JSON systems.
            - 'error' (str|None): Error message if the command failed.
    """
    global MODULE_CACHE
    now = time.time()

    if use_cache and MODULE_CACHE["avail"] and (now - MODULE_CACHE["avail"]["ts"] < CACHE_TTL):
        data = MODULE_CACHE["avail"]["data"]
    else:
        result = run_module_cmd("avail --json")
        try:
            data = json.loads(result.stdout)
            MODULE_CACHE["avail"] = {"data": data, "ts": now}
        except json.JSONDecodeError:
            result = run_module_cmd("avail")
            data = {"raw_text": result.stderr if not result.stdout else result.stdout}

    if query and isinstance(data, list):
        filtered = []
        for entry in data:
            entry_mods = [m for m in entry.get("modules", []) if query in m]
            if entry_mods:
                filtered.append({"path": entry.get("path"), "modules": entry_mods})
        return {"success": True, "data": filtered, "error": None}

    return {"success": True, "data": data, "error": None}


def module_show(
    module_name: Annotated[str, "The full name/version of the module to inspect."],
) -> ModuleQueryResult:
    """
    Shows detailed information about a module, including the environment variables it modifies.

    Args:
        module_name: The exact name of the module (e.g., 'python/3.11.2').

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the module was found.
            - 'data' (dict): Contains 'bin_paths', 'lib_paths', and the 'raw' modulefile content.
            - 'error' (str|None): Error message if the module does not exist.
    """
    global MODULE_CACHE
    now = time.time()

    if module_name in MODULE_CACHE["show"]:
        cached = MODULE_CACHE["show"][module_name]
        if now - cached["ts"] < CACHE_TTL:
            return {"success": True, "data": cached["data"], "error": None}

    result = run_module_cmd(f"show {module_name}")
    if result.returncode != 0:
        return {"success": False, "data": {}, "error": result.stderr.strip()}

    output = result.stderr + result.stdout
    parsed_info = {"raw": output, "bin_paths": [], "lib_paths": []}

    for line in output.splitlines():
        if "prepend-path" in line or "append-path" in line:
            if "PATH" in line and "LD_LIBRARY_PATH" not in line:
                parsed_info["bin_paths"].append(line.split()[-1])
            elif "LD_LIBRARY_PATH" in line:
                parsed_info["lib_paths"].append(line.split()[-1])

    MODULE_CACHE["show"][module_name] = {"data": parsed_info, "ts": now}
    return {"success": True, "data": parsed_info, "error": None}


def module_load_instruction(
    modules: Annotated[List[str], "List of module names to load."],
) -> ModuleQueryResult:
    """
    Generates a shell-ready command string for loading the specified modules.

    Args:
        modules: A list of strings representing module names.

    Returns:
        A dictionary containing:
            - 'success' (bool): True.
            - 'data' (dict): Contains 'command' (the load string) and 'instruction'.
            - 'error' (None).
    """
    load_cmd = f"module load {' '.join(modules)}"
    return {
        "success": True,
        "data": {
            "command": load_cmd,
            "instruction": f"Run your next command prefixed by: '{load_cmd} && ...'",
        },
        "error": None,
    }


def module_get_path() -> ModuleQueryResult:
    """
    Retrieve the current MODULEPATH configuration.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if MODULEPATH is set.
            - 'data' (dict): Contains 'modulepath' as a list of directory strings.
            - 'error' (str|None): Error if environment variable is missing.
    """
    path = os.environ.get("MODULEPATH", "")
    return {
        "success": True,
        "data": {"modulepath": path.split(":")},
        "error": None if path else "MODULEPATH is not set.",
    }
