import json
import os
from pathlib import Path


def list_directory(path: str = ".") -> str:
    """
    List files and directories in the specified path.
    Useful for checking if files exist or understanding the project structure.

    Args:
        path: The directory path to list (defaults to current directory).
    """
    try:
        p = Path(path).resolve()

        # Security/Sanity check: Ensure it exists
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        if not p.is_dir():
            return f"Error: Path '{path}' is not a directory."

        # Get detailed list
        items = []
        for item in p.iterdir():
            type_label = "DIR" if item.is_dir() else "FILE"
            size = item.stat().st_size if item.is_file() else 0
            items.append(f"[{type_label}] {item.name} ({size} bytes)")

        if not items:
            return f"Directory '{path}' is empty."

        return "\n".join(items)

    except Exception as e:
        return f"Error listing directory: {str(e)}"


def read_file(path: str) -> str:
    """
    Read the contents of a file.

    Args:
        path: The path to the file to read.
    """
    try:
        p = Path(path).resolve()
        if not p.exists():
            return f"Error: File '{path}' not found."
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        with open(p, "r", encoding="utf-8") as f:
            content = f.read()

        return content

    except UnicodeDecodeError:
        return f"Error: File '{path}' is binary or not UTF-8 encoded."
    except Exception as e:
        return f"Error reading file: {str(e)}"


def write_file(path: str, content: str) -> str:
    """
    Write content to a file. Creates directories if they don't exist.

    Args:
        path: The path where the file should be written.
        content: The text content to write.
    """
    try:
        p = Path(path).resolve()

        # Ensure parent directory exists
        p.parent.mkdir(parents=True, exist_ok=True)

        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote {len(content)} bytes to '{path}'."

    except Exception as e:
        return f"Error writing file: {str(e)}"
