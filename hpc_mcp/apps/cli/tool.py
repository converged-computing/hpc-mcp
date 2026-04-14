import os
import re
import subprocess
from typing import Annotated, Any, Dict, List, Optional


def get_command_help(
    binary_path: Annotated[
        str, "The absolute path to the application binary (e.g., '/usr/bin/lmp')."
    ],
    subcommand: Annotated[
        Optional[str], "An optional subcommand to get specific help for (e.g., 'submit')."
    ] = None,
    request_man_page: Annotated[
        bool,
        "If True, attempts to retrieve the system 'man' page. If False, uses CLI flags like --help.",
    ] = False,
) -> Annotated[
    Dict[str, Any], "A dictionary containing the help content, success status, and error details."
]:
    """
    Retrieves documentation for a binary using either standard CLI help flags or system manual pages.

    Guidance for Usage:
    Call with request_man_page=False (default) first to see quick usage flags and subcommands.
    You can use the cli help to verify subcommands, and further query them.
    If CLI help is missing details, set request_man_page=True.

    Returns:
        A dictionary with:
        - success (bool): True if any documentation was successfully retrieved.
        - binary_found (bool): True if the binary path exists and is executable.
        - help_content (str): The plain-text documentation retrieved.
        - method_used (str): Description of the command that produced the output.
        - return_code (int): The exit status of the help/man command.
        - error (Optional[str]): Detailed error message if the attempt failed.
    """
    # 1. Path and Permissions Validation
    if not os.path.exists(binary_path):
        return {
            "success": False,
            "binary_found": False,
            "help_content": "",
            "return_code": -1,
            "method_used": "none",
            "error": f"The path '{binary_path}' does not exist.",
        }

    if not os.access(binary_path, os.X_OK):
        return {
            "success": False,
            "binary_found": True,
            "help_content": "",
            "return_code": -1,
            "method_used": "none",
            "error": f"The file at '{binary_path}' is not executable.",
        }

    # Man pages!
    if request_man_page:
        return get_man_page(binary_path)

    # CLI Flags (help is go style commands)
    variants: List[List[str]] = []
    if subcommand:
        variants.append([binary_path, subcommand, "-h"])
        variants.append([binary_path, subcommand, "--help"])
        variants.append([binary_path, "help", subcommand])
    else:
        variants.append([binary_path, "-h"])
        variants.append([binary_path, "--help"])
        variants.append([binary_path, "help"])

    last_error = ""
    last_rc = 0

    for cmd in variants:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = (result.stdout + "\n" + result.stderr).strip()

            # Not sure if we need this - testing
            keywords = ["usage:", "options:", "arguments:", "help:", "commands:"]
            is_help = any(k in output.lower() for k in keywords)
            if not is_help:
                print(f"Output determined not help (verify): {output}")

            if result.returncode == 0 or (is_help and len(output) > 50):
                return {
                    "success": True,
                    "binary_found": True,
                    "help_content": output,
                    "return_code": result.returncode,
                    "method_used": " ".join(cmd),
                    "error": None,
                }

            last_rc = result.returncode
            last_error = output
        except subprocess.TimeoutExpired:
            last_error = "Command timed out."
        except Exception as e:
            last_error = str(e)

    return {
        "success": False,
        "binary_found": True,
        "help_content": last_error,
        "return_code": last_rc,
        "method_used": "CLI flag exhaustion",
        "error": "Could not extract help information using standard CLI flags.",
    }


def get_man_page(binary_path):
    """
    Get the man page help for a binary. This is a helper function.
    I think it is better to give agents access to one client help
    function and have them decide how to use it.
    """
    binary_name = os.path.basename(binary_path)
    try:
        # -P cat ensures non-blocking output
        man_proc = subprocess.Popen(
            ["man", "-P", "cat", binary_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # col -b strips backspace in terminal bolding
        clean_proc = subprocess.run(
            ["col", "-b"],
            input=man_proc.communicate()[0],
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = clean_proc.stdout.strip()
        if man_proc.returncode == 0 and output:
            return {
                "success": True,
                "binary_found": True,
                "help_content": clean_proc.stdout.strip(),
                "return_code": 0,
                "method_used": f"man -P cat {binary_name} | col -b",
                "error": None,
            }

        # Failure case
        return {
            "success": False,
            "binary_found": True,
            "help_content": "",
            "return_code": man_proc.returncode,
            "method_used": "man",
            "error": f"No manual entry found for '{binary_name}'. Output: {output}",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "binary_found": True,
            "help_content": "",
            "return_code": -1,
            "method_used": "man",
            "error": "System 'man' or 'col' utilities not found.",
        }
