import functools
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import hpc_mcp.utils as utils

SANDBOX_ENABLED = utils.envar_get_boolean("HPCMCP_FILESYSTEM_SANDBOX")
DATA_ROOT = os.environ.get("HPCMCP_FILESYSTEM_DATA_ROOT")
RESULT_ROOT = os.environ.get("HPCMCP_FILESYSTEM_RESULT_ROOT")
LIMIT = utils.envar_get_integer("HPCMCP_FILESYSTEM_TOKEN_LIMIT")

print(f"    SANDBOX ENABLED: {SANDBOX_ENABLED}")
print(f"        RESULT ROOT: {RESULT_ROOT}")
print(f"          DATA ROOT: {DATA_ROOT}")
print(f"              LIMIT: {LIMIT}")

ToolResult = Annotated[
    Dict[str, Any],
    "A standardized response containing 'success' (bool) and either data or 'error'.",
]

NativeQueryResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), 'output' (the tool result string), "
    "and 'tool_used' (grep or jq).",
]

DirectoryListingResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), a list of 'items' (name, type, size), "
    "the 'absolute_path' resolved, and optional 'error'.",
]

FileReadResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), 'content' (string), 'bytes_read', "
    "'remaining_bytes', and a 'message' describing the window read.",
]

FileWriteResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), 'bytes_written', and the resolved 'path'.",
]

JSONStructureResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), and a 'structure' map showing keys and data types.",
]

JSONQueryResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), the 'query_result' (any), and optional 'note' if truncated.",
]

FileSystemFindResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), a list of 'matches' (absolute paths), and optional 'message'.",
]


def _has_tool(name: str) -> bool:
    """
    Internal check for system binaries.
    """
    return shutil.which(name) is not None


def validate_access(path: str, mode: Literal["read", "write"] = "read") -> Union[Path, str]:
    """
    Internal helper to resolve paths and enforce sandbox constraints.
    Returns a Path object if valid, otherwise returns a string error message.
    """
    try:
        p = Path(path).resolve()
        if not SANDBOX_ENABLED:
            return p

        if not DATA_ROOT or not RESULT_ROOT:
            return "Configuration Error: HPCMCP_FILESYSTEM_DATA_ROOT or RESULT_ROOT is not defined while sandbox is enabled."

        data_p = Path(DATA_ROOT).resolve()
        result_p = Path(RESULT_ROOT).resolve()

        is_in_data = p.is_relative_to(data_p)
        is_in_result = p.is_relative_to(result_p)

        if mode == "write":
            if not is_in_result:
                return f"Security Error: Write access denied. Path '{path}' is outside the allowed RESULT_ROOT."
            return p

        if mode == "read":
            if not (is_in_data or is_in_result):
                return f"Security Error: Read access denied. Path '{path}' is outside allowed DATA or RESULT roots."
            return p

    except Exception as e:
        return f"Path Resolution Error: {str(e)}"
    return "Unknown Path Error"


def filesystem_tool(mode: Literal["read", "write"] = "read"):
    """
    Decorator to wrap filesystem tools with sandbox and error handling logic.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            path_val = kwargs.get("path") or (args[0] if args else None)
            if path_val is not None:
                validated = validate_access(path_val, mode=mode)
                if isinstance(validated, str):
                    return {"success": False, "error": validated}
                if "path" in kwargs:
                    kwargs["path"] = str(validated)
                elif args:
                    args_list = list(args)
                    args_list[0] = str(validated)
                    args = tuple(args_list)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return {"success": False, "error": f"Tool execution failed: {str(e)}"}

        return wrapper

    return decorator


@filesystem_tool(mode="read")
def filesystem_list_directory(
    path: Annotated[
        Optional[str], "The directory path to list. Defaults to current directory."
    ] = None,
) -> DirectoryListingResult:
    """
    Lists the contents of a directory, providing metadata for each file and folder found.

    This tool is useful for exploring the filesystem and understanding the directory
    structure before performing file operations or data extraction.

    Args:
        path: The target directory path.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the directory was successfully accessed.
            - 'items' (list[dict]): Objects containing 'name', 'type' (DIR/FILE), and 'size_bytes'.
            - 'absolute_path' (str): The fully resolved path that was listed.
    """
    p = Path(path or ".")
    items = []
    for item in p.iterdir():
        items.append(
            {
                "name": item.name,
                "type": "DIR" if item.is_dir() else "FILE",
                "size_bytes": item.stat().st_size if item.is_file() else 0,
            }
        )
    return {"success": True, "items": items, "absolute_path": str(p)}


@filesystem_tool(mode="read")
def filesystem_read_file(
    path: Annotated[str, "The path to the file to be read."],
    offset: Annotated[int, "The byte offset to start reading from."] = 0,
    limit: Annotated[int, "The maximum characters to read to prevent token overflow."] = 5000,
) -> FileReadResult:
    """
    Reads a chunk of a text file starting from a specific offset.

    Use this tool to inspect files that are too large to read in a single request.
    It returns metadata about remaining bytes to help you decide if more reads are needed.

    Args:
        path: The path to the file.
        offset: The position in the file to start reading.
        limit: The maximum number of characters to return.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the read was successful.
            - 'content' (str): The raw text read from the file.
            - 'bytes_read' (int): The number of characters actually returned.
            - 'remaining_bytes' (int): How many bytes are left in the file after this chunk.
    """
    limit = min(limit, LIMIT) if LIMIT is not None else limit
    with open(path, "r", encoding="utf-8") as f:
        f.seek(offset)
        content = f.read(limit)

    total_size = Path(path).stat().st_size
    remaining = max(0, total_size - (offset + len(content)))

    return {
        "success": True,
        "content": content,
        "bytes_read": len(content),
        "remaining_bytes": remaining,
        "message": f"Showing bytes {offset} to {offset + len(content)} of {total_size}.",
    }


@filesystem_tool(mode="write")
def filesystem_write_file(
    path: Annotated[str, "The target path where the file will be created."],
    content: Annotated[str, "The text content to be written."],
) -> FileWriteResult:
    """
    Writes text content to a file, creating parent directories automatically.

    In sandbox mode, this tool is restricted to writing only within the
    HPCMCP_FILESYSTEM_RESULT_ROOT.

    Args:
        path: The destination path.
        content: The string content to write.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the write completed.
            - 'bytes_written' (int): Total size of the content written.
            - 'path' (str): The resolved absolute path where the file was saved.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return {"success": True, "path": str(p), "bytes_written": len(content)}


@filesystem_tool(mode="read")
def filesystem_get_json_structure(
    path: Annotated[str, "Path to the JSON file to analyze."],
) -> JSONStructureResult:
    """
    Analyzes a JSON file and returns its schema (keys and types) without the data values.

    Use this tool to understand the hierarchy of large data files before using
    precision query tools. It helps identify where Figures of Merit (FOMs) are stored.

    Args:
        path: The path to the JSON file.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the JSON was parsed.
            - 'structure' (dict): A map showing keys and their value types (e.g., 'list[float]').
    """

    def get_structure(data):
        if isinstance(data, dict):
            return {k: get_structure(v) for k, v in data.items()}
        elif isinstance(data, list):
            inner = get_structure(data[0]) if data else "empty"
            return f"list[{inner}]"
        else:
            return type(data).__name__

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"success": True, "structure": get_structure(data)}


@filesystem_tool(mode="read")
def filesystem_query_json(
    path: Annotated[str, "Path to the JSON file."],
    query: Annotated[str, "Dot-notation query string (e.g., 'results.iterations[0].fom')."],
    limit: Annotated[int, "The maximum characters to read to prevent token overflow."] = 5000,
) -> JSONQueryResult:
    """
    Extracts a specific value from a JSON file using a dot-notation query path.

    This is the most efficient way to get specific data (like Figures of Merit)
    from large JSON files without loading the entire file into context.

    Args:
        path: The path to the JSON file.
        query: The dot-notation path to the desired key. Use digits for list indices.
        limit: The maximum number of characters to return.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the key was found.
            - 'query_result' (any): The data found at that path.
            - 'note' (str, optional): A warning if the result was truncated due to size.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    parts = query.replace("[", ".").replace("]", "").split(".")
    current = data
    try:
        for part in parts:
            if part.isdigit():
                current = current[int(part)]
            else:
                current = current[part]
    except (KeyError, IndexError, TypeError):
        return {"success": False, "error": f"Query '{query}' not found in JSON."}

    limit = min(limit, LIMIT) if LIMIT is not None else limit
    resp_str = json.dumps(current)
    if len(resp_str) > 10000:
        return {
            "success": True,
            "query_result": resp_str[:10000] + "... [Truncated]",
            "note": "Result is too large. Refine your query path.",
        }

    return {"success": True, "query_result": current}


@filesystem_tool(mode="read")
def filesystem_find(
    name: Annotated[str, "The name or glob pattern to search for."],
    path: Annotated[str, "The root directory to start searching from."],
    type: Annotated[Literal["file", "directory"], "The type of item to find."] = "file",
) -> FileSystemFindResult:
    """
    Recursively searches for files or directories starting from a root path.

    Args:
        name: The filename, directory name, or glob pattern (e.g., '*.json').
        path: The directory to start the recursive search from.
        type: Whether to search for 'file' or 'directory'.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the search completed.
            - 'matches' (list[str]): Absolute paths to items found (limit 20).
            - 'message' (str, optional): Status message or result count.
    """
    p = Path(path)
    matches = []
    for item in p.rglob(name):
        if type == "file" and item.is_file():
            matches.append(str(item))
        elif type == "directory" and item.is_dir():
            matches.append(str(item))

        if len(matches) >= 20:
            return {"success": True, "matches": matches, "message": "Limit of 20 results reached."}

    return {"success": True, "matches": matches}


@filesystem_tool(mode="read")
def filesystem_grep(
    path: Annotated[str, "The absolute or relative path to the file to search."],
    pattern: Annotated[str, "The regex pattern to search for (Extended Regex format)."],
    case_insensitive: Annotated[bool, "Toggle case-insensitive matching."] = True,
    context_lines: Annotated[int, "Number of lines of context to include around matches."] = 2,
    limit: Annotated[int, "The maximum number of tokens (length) to return."] = 2000,
) -> NativeQueryResult:
    """
    Performs a high-performance text search using the system 'grep' utility.

    This is highly scalable and can search through multi-gigabyte files (logs, CSVs, or JSON)
    without loading them into memory. It returns line numbers and context to help
    the agent understand the surrounding data.

    Args:
        path: Target file path.
        pattern: Regex pattern to find.
        case_insensitive: If True, uses the '-i' flag.
        context_lines: Uses the '-C' flag to show surrounding lines.
        limit: Uses the '-m' flag to stop searching after N matches.

    Returns:
        A dictionary with the matching lines and metadata.
    """
    if not _has_tool("grep"):
        return {"success": False, "error": "System tool 'grep' not found."}

    # Construct safe grep command
    cmd = ["grep", "-n", "-E"]
    if case_insensitive:
        cmd.append("-i")
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    cmd.extend(["-m", str(limit), pattern, path])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 1:
        return {"success": True, "output": "No matches found.", "tool_used": "grep"}
    if result.returncode >= 2:
        return {"success": False, "error": result.stderr, "tool_used": "grep"}

    # Final safety truncation for token protection
    output = result.stdout
    limit = min(limit, LIMIT) if LIMIT is not None else limit
    if len(output) > limit:
        output = output[:limit] + "\n... [Output truncated for size]"

    return {"success": True, "output": output, "tool_used": "grep"}


@filesystem_tool(mode="read")
def filesystem_query_jq(
    path: Annotated[str, "The path to the JSON file."],
    query: Annotated[str, "The jq query string (e.g., '.results[] | select(.fom > 10)')."],
    compact: Annotated[bool, "Whether to return compact JSON (recommended for agents)."] = True,
) -> NativeQueryResult:
    """
    Processes and filters JSON data using the native 'jq' utility.

    This is the most scalable way to extract specific values or sub-objects from
    large JSON files. It offloads processing to C and avoids loading large
    JSON structures into Python memory.

    Args:
        path: Path to the JSON file.
        query: Standard jq filter/query string.
        compact: If True, uses '-c' to output single-line JSON to save tokens.

    Returns:
        The filtered results or error message.
    """
    if not _has_tool("jq"):
        return {"success": False, "error": "System tool 'jq' not found."}

    cmd = ["jq", "-M"]  # -M for monochrome
    if compact:
        cmd.append("-c")

    cmd.extend([query, path])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {"success": False, "error": result.stderr, "tool_used": "jq"}

    output = result.stdout
    if len(output) > 15000:
        output = output[:15000] + "\n... [Output truncated for size]"

    try:
        output = json.loads(output)
    except:
        pass
    return {"success": True, "output": output, "tool_used": "jq"}



@filesystem_tool(mode="read")
def filesystem_get_json_schema_paths(
    path: Annotated[str, "The path to the JSON file to analyze."]
) -> ToolResult:
    """
    Returns a unique list of all data paths within a JSON file in dot-notation.
    
    This tool collapses array indices (e.g., [0], [1]) into '[]' to show 
    the schema structure. Use this to identify the exact path needed for 
    high-performance jq queries.
    """
    if not _has_tool("jq"):
        return {"success": False, "error": "System tool 'jq' is required."}

    # Stream all paths using jq. This is memory efficient for large files.
    cmd = ["jq", "-c", "tostream | select(length > 1) | .[0]", path]
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0:
        return {"success": False, "error": res.stderr}

    unique_paths = set()
    for line in res.stdout.splitlines():
        try:
            path_list = json.loads(line)
            parts = []
            for part in path_list:
                if isinstance(part, int):
                    # Attach [] to the previous key, or add [] if it's the root
                    if parts:
                        if not parts[-1].endswith("[]"):
                            parts[-1] += "[]"
                    else:
                        parts.append("[]")
                else:
                    parts.append(str(part))
            unique_paths.add(".".join(parts))
        except:
            continue

    # Return sorted list for consistent agent context
    return {
        "success": True, 
        "paths": sorted(list(unique_paths)),
        "message": f"Found {len(unique_paths)} unique schema paths."
    }


@filesystem_tool(mode="read")
def filesystem_get_json_structure(
    path: Annotated[str, "Path to the JSON file to analyze."],
) -> NativeQueryResult:
    """
    Discovers the top-level structure and keys of a JSON file.

    Uses 'jq' if available for high performance on large files. Recommended as
    a first step before performing complex data extraction.
    """
    if _has_tool("jq"):
        # This query returns keys for objects or keys for the first element of an array
        query = 'if type == "array" then .[0] | keys else keys end'
        return filesystem_query_jq(path=path, query=query)

    # Python fallback for small files if jq is missing
    with open(path, "r") as f:
        data = json.load(f)
    keys = list(data.keys()) if isinstance(data, dict) else "array"
    return {"success": True, "output": f"Root keys: {keys}", "tool_used": "python_fallback"}


@filesystem_tool(mode="read")
def filesystem_batch_extract_to_file(
    root_path: Annotated[str, "The directory to search within (e.g., the application root)."],
    file_pattern: Annotated[
        str, "The glob pattern for files (e.g., '**/iteration_*/result.json')."
    ],
    jq_query: Annotated[
        str, "The jq query to apply to each file (e.g., '{fom: .metrics.fom, status: .status}')."
    ],
    output_filename: Annotated[
        str, "The name of the file to save results into within the RESULT_ROOT."
    ],
    is_test: Annotated[
        bool,
        "If True, only processes 2 files and returns the result to the agent for verification.",
    ] = True,
) -> ToolResult:
    """
    Finds multiple JSON files, extracts data using jq, and saves the consolidated
    result directly to the RESULT_ROOT.

    This tool is designed for high-efficiency data gathering. Instead of sending
    thousands of results back to the API, it writes them to a file for later
    processing or plotting.

    TEST MODE (is_test=True):
    Returns the extracted data for the first 2 matching files so you can verify
    your jq query is correct.

    PRODUCTION MODE (is_test=False):
    Processes all matching files, saves the output to the RESULT_ROOT, and
    ONLY returns a list of files that had errors.

    Returns:
        Test Mode: A dictionary with 'test_results' and the 'target_path'.
        Production Mode: A dictionary with 'errors' (if any) and 'saved_to' path.
    """
    if not _has_tool("jq"):
        return {"success": False, "error": "System tool 'jq' is required for batch extraction."}

    # Resolve and Validate output path
    # Even though the decorator validates root_path, we must manually validate
    # the output_filename because it goes to the RESULT_ROOT.
    if not RESULT_ROOT:
        return {"success": False, "error": "HPCMCP_FILESYSTEM_RESULT_ROOT is not configured."}

    target_path = Path(RESULT_ROOT).resolve() / output_filename
    if not target_path.is_relative_to(Path(RESULT_ROOT).resolve()):
        return {"success": False, "error": f"Security Error: Output must be within {RESULT_ROOT}"}

    # Find matching files
    search_root = Path(root_path)
    all_files = [f for f in search_root.rglob(file_pattern) if f.is_file()]

    if not all_files:
        return {
            "success": False,
            "error": f"No files found matching pattern '{file_pattern}' in '{root_path}'.",
        }

    # Handle Test Mode
    files_to_process = all_files[:2] if is_test else all_files

    successful_results = {}
    errors = []

    for f in files_to_process:
        f_str = str(f.resolve())

        # Check read access for each found file
        if isinstance(validate_access(f_str, mode="read"), str):
            errors.append({"file": f_str, "error": "Access Denied"})
            continue

        cmd = ["jq", "-c", "-M", jq_query, f_str]
        res = subprocess.run(cmd, capture_output=True, text=True)

        if res.returncode == 0:
            try:
                successful_results[f_str] = json.loads(res.stdout)
            except json.JSONDecodeError:
                successful_results[f_str] = res.stdout.strip()
        else:
            errors.append({"file": f_str, "error": res.stderr.strip()})

    # Try loading as json
    try:
        successful_results = json.loads(successful_results)
    except:
        pass

    # Test returns the content
    if is_test:
        return {
            "success": True,
            "is_test_run": True,
            "test_results": successful_results,
            "potential_errors_in_sample": errors,
            "message": (
                f"Test complete. Verified {len(successful_results)} files. "
                f"Full run would process {len(all_files)} files and save to '{output_filename}'. "
                "If this looks correct, call again with is_test=False."
            ),
            "target_path": str(target_path),
        }
    else:
        # Production (non test) saves to file
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as out_f:
                json.dump(successful_results, out_f, indent=2)

            return {
                "success": True,
                "is_test_run": False,
                "saved_to": str(target_path),
                "total_files_processed": len(all_files),
                "successful_extractions": len(successful_results),
                "errors": errors,  # Only returns the problematic files
                "message": f"Consolidated data from {len(successful_results)} files into {output_filename}.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to write consolidated file: {str(e)}"}


@filesystem_tool(mode="read")
def filesystem_batch_extract_to_file_test(
    root_path: Annotated[str, "The directory to search within (e.g., the application root)."],
    file_pattern: Annotated[
        str, "The glob pattern for files (e.g., '**/iteration_*/result.json')."
    ],
    jq_query: Annotated[
        str, "The jq query to apply to each file (e.g., '{fom: .metrics.fom, status: .status}')."
    ],
    output_filename: Annotated[
        str, "The name of the file to save results into within the RESULT_ROOT."
    ],
) -> ToolResult:
    """
    Finds multiple JSON files, extracts data using jq, and saves the consolidated
    result directly to the RESULT_ROOT.

    This tool is designed for high-efficiency data gathering. Instead of sending
    thousands of results back to the API, it writes them to a file for later
    processing or plotting.

    You MUST call this before filesystem_batch_extract_to_file to verify your correctness.

    Returns:
        Test Mode: A dictionary with 'test_results' and the 'target_path'.
        Production Mode: A dictionary with 'errors' (if any) and 'saved_to' path.
    """
    return filesystem_batch_extract_to_file(
        root_path, file_pattern, jq_query, output_filename, True
    )


@filesystem_tool(mode="read")
def filesystem_get_system_capabilities() -> ToolResult:
    """
    Returns the current sandbox configuration and available system tools.

    Use this at the start of a session to understand where you can read/write
    and which high-performance tools (jq, grep) are available.
    """
    return {
        "success": True,
        "sandbox_enabled": SANDBOX_ENABLED,
        "roots": {"DATA_ROOT": DATA_ROOT, "RESULT_ROOT": RESULT_ROOT},
        "tools_available": {"jq": _has_tool("jq"), "grep": _has_tool("grep")},
    }


@filesystem_tool(mode="read")
def filesystem_summarize_result_file(
    path: Annotated[str, "Path to a JSON file in the RESULT_ROOT containing extracted data."],
    numeric_key: Annotated[str, "The key to perform statistics on (e.g., 'fom')."],
) -> ToolResult:
    """
    Calculates basic statistics (min, max, mean, count) for a numeric field
    within a consolidated result file.

    Use this to verify your final report without reading the entire file
    back into your context window.
    """
    with open(path, "r") as f:
        data = json.load(f)

    # Handle the dictionary format produced by batch_extract_to_file
    values = []
    for entry in data.values():
        if isinstance(entry, dict) and numeric_key in entry:
            try:
                values.append(float(entry[numeric_key]))
            except (ValueError, TypeError):
                continue
        elif isinstance(entry, (int, float)):  # In case it's a direct mapping
            values.append(float(entry))

    if not values:
        return {"success": False, "error": f"No numeric data found for key '{numeric_key}'."}

    return {
        "success": True,
        "stats": {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        },
    }


@filesystem_tool(mode="write")  # Mode write allows deletion in RESULT_ROOT
def filesystem_remove_file(
    path: Annotated[str, "The path to the file to delete (must be in RESULT_ROOT)."],
) -> ToolResult:
    """
    Deletes a file from the RESULT_ROOT.

    Use this to clean up intermediate scratch files or incorrect results
    to keep the workspace tidy.
    """
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": "File does not exist."}

    if p.is_dir():
        return {"success": False, "error": "Use a directory removal tool for folders."}

    p.unlink()
    return {"success": True, "message": f"Successfully deleted {p.name}."}


@filesystem_tool(mode="read")
def filesystem_tail_log(
    path: Annotated[str, "Path to the log or text file."],
    lines: Annotated[int, "Number of lines to retrieve from the end."] = 50,
) -> ToolResult:
    """
    Retrieves the last N lines of a file.

    This is the most efficient way to check if a long-running process
    completed successfully or to see the latest error in a log file.
    """
    if _has_tool("tail"):
        cmd = ["tail", "-n", str(lines), path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return {"success": True, "content": res.stdout}

    # Python fallback
    with open(path, "r") as f:
        content = f.readlines()
        return {"success": True, "content": "".join(content[-lines:])}


@filesystem_tool(mode="read")
def filesystem_find_file(
    name: Annotated[str, "The exact name of the file to search for (e.g., 'config.yaml')."],
    root: Annotated[
        Optional[str], "The directory to start the search from. Defaults to the current directory."
    ] = ".",
    limit: Annotated[int, "The maximum number of matches to return."] = 10,
) -> FileSystemFindResult:
    """
    Recursively searches for a file by name starting from a specified root directory.

    Args:
        name: The filename to search for. Must not contain path separators.
        root: The starting point for the recursive search.
        limit: Caps the number of results to prevent excessive output.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the search completed without error.
            - 'matches' (list[str]): A list of absolute paths to found files.
            - 'error' (str, optional): Error message if root is invalid or search failed.
    """
    limit = min(limit, LIMIT) if LIMIT is not None else limit

    # Security: Ensure name is just a filename, not a path
    if os.path.basename(name) != name:
        return {"success": False, "error": "The 'name' argument must be a filename, not a path."}

    try:
        search_root = Path(root or ".").resolve()
        if not search_root.exists() or not search_root.is_dir():
            return {"success": False, "error": f"Search root '{root}' is not a valid directory."}

        # Recursive search using glob
        matches = []
        for p in search_root.rglob(name):
            if p.is_file():
                matches.append(str(p))
            if len(matches) >= limit:
                break

        return {
            "success": True,
            "matches": matches,
            "message": (
                f"Found {len(matches)} match(es) for '{name}'." if matches else "No matches found."
            ),
        }
    except Exception as e:
        return {"success": False, "error": f"Error searching for file: {str(e)}"}


@filesystem_tool(mode="read")
def filesystem_find_directory(
    name: Annotated[str, "The exact name of the directory to search for (e.g., 'src')."],
    root: Annotated[
        Optional[str], "The directory to start the search from. Defaults to the current directory."
    ] = ".",
    limit: Annotated[int, "The maximum number of matches to return."] = 10,
) -> FileSystemFindResult:
    """
    Recursively searches for a directory by name starting from a specified root directory.

    Args:
        name: The directory name to search for. Must not contain path separators.
        root: The starting point for the recursive search.
        limit: Caps the number of results to prevent excessive output.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the search completed without error.
            - 'matches' (list[str]): A list of absolute paths to found directories.
            - 'error' (str, optional): Error message if root is invalid or search failed.
    """
    limit = min(limit, LIMIT) if LIMIT is not None else limit

    # Security: Ensure name is just a name, not a path
    if os.path.basename(name) != name:
        return {"success": False, "error": "The 'name' argument must be a name, not a path."}

    try:
        search_root = Path(root or ".").resolve()
        if not search_root.exists() or not search_root.is_dir():
            return {"success": False, "error": f"Search root '{root}' is not a valid directory."}

        matches = []
        for p in search_root.rglob(name):
            if p.is_dir():
                matches.append(str(p))
            if len(matches) >= limit:
                break

        return {
            "success": True,
            "matches": matches,
            "message": (
                f"Found {len(matches)} match(es) for directory '{name}'."
                if matches
                else "No matches found."
            ),
        }
    except Exception as e:
        return {"success": False, "error": f"Error searching for directory: {str(e)}"}
