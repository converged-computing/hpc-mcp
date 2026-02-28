import json
import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union

DirectoryListingResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), a list of 'items' (each with name, type, and size), "
    "and optional 'error' or 'message' strings.",
]

FileReadResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), the 'content' string of the file if successful, "
    "and an 'error' string if the read failed.",
]

FileWriteResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), the number of 'bytes_written', the resolved 'path', "
    "and a descriptive 'message' or 'error'.",
]

FileSystemFindResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), a list of 'matches' (absolute path strings), "
    "and optional 'error' or 'message' strings.",
]


def filesystem_list_directory(
    path: Annotated[
        Optional[str], "The directory path to list. Defaults to the current working directory."
    ] = None,
) -> DirectoryListingResult:
    """
    Lists the contents of a directory, providing metadata for each file and folder found.

    This tool is useful for exploring the filesystem, verifying the existence of
    project files, or understanding the directory structure before performing file operations.

    Args:
        path: The target directory path. If None, it defaults to the current directory.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the directory was successfully accessed.
            - 'items' (list[dict]): A list of objects containing 'name', 'type' (DIR/FILE),
              and 'size_bytes'.
            - 'error' (str, optional): A descriptive error if the path is invalid or inaccessible.
            - 'message' (str, optional): Information about empty directories.
    """
    if path is None:
        path = "."

    try:
        p = Path(path).resolve()

        if not p.exists():
            return {"success": False, "error": f"Error: Path '{path}' does not exist."}
        if not p.is_dir():
            return {"success": False, "error": f"Error: Path '{path}' is not a directory."}

        items = []
        for item in p.iterdir():
            type_label = "DIR" if item.is_dir() else "FILE"
            size = item.stat().st_size if item.is_file() else 0
            items.append({"type": type_label, "name": item.name, "size_bytes": size})

        if not items:
            return {"success": True, "items": [], "message": f"Directory '{path}' is empty."}

        return {"success": True, "items": items}

    except Exception as e:
        return {"success": False, "error": f"Error listing directory: {str(e)}"}


def filesystem_read_file(
    path: Annotated[str, "The relative or absolute path to the file to be read."],
) -> FileReadResult:
    """
    Reads and returns the full text content of a file.

    Use this tool to inspect script contents, configuration files, or data files.
    The file must be UTF-8 encoded.

    Args:
        path: The path to the file.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the file was read successfully.
            - 'content' (str or None): The raw text content of the file.
            - 'error' (str, optional): A descriptive error if the file is missing,
              is a directory, or has an incompatible encoding.
    """
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "content": None, "error": f"Error: File '{path}' not found."}
        if not p.is_file():
            return {"success": False, "content": None, "error": f"Error: '{path}' is not a file."}

        with open(p, "r", encoding="utf-8") as f:
            content = f.read()

        return {"success": True, "content": content}

    except UnicodeDecodeError:
        return {
            "success": False,
            "content": None,
            "error": f"Error: File '{path}' is binary or not UTF-8 encoded.",
        }
    except Exception as e:
        return {"success": False, "content": None, "error": f"Error reading file: {str(e)}"}


def filesystem_write_file(
    path: Annotated[str, "The target path where the file will be created or overwritten."],
    content: Annotated[str, "The text content to be written to the file."],
) -> FileWriteResult:
    """
    Writes text content to a file, creating any necessary parent directories automatically.

    This tool should be used to create batch scripts, configuration files, or to
    save results to the filesystem. If the file already exists, it will be overwritten.

    Args:
        path: The destination path for the file.
        content: The string content to write.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the write operation completed.
            - 'bytes_written' (int): Total size of the content written.
            - 'path' (str): The resolved absolute path where the file was saved.
            - 'message' (str, optional): A success confirmation message.
            - 'error' (str, optional): A descriptive error if write permissions
              fail or the path is invalid.
    """
    try:
        p = Path(path).resolve()

        # Ensure parent directory exists
        p.parent.mkdir(parents=True, exist_ok=True)

        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "success": True,
            "bytes_written": len(content),
            "path": str(p),
            "message": f"Successfully wrote {len(content)} bytes to '{path}'.",
        }

    except Exception as e:
        return {"success": False, "error": f"Error writing file: {str(e)}"}


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
