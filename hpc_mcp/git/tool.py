import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union

GitOperationResult = Annotated[
    Dict[str, Any],
    "A dictionary containing 'success' (bool), the raw 'output' string from git, "
    "and an 'error' string if the operation failed.",
]


def check_git() -> str:
    """Ensures git is installed on the system."""
    git_path = shutil.which("git")
    if not git_path:
        raise ValueError("git is not present on the system path.")
    return git_path


def run_git_command(args: List[str], cwd: Union[str, Path]) -> GitOperationResult:
    """Safely executes a git command in a specific directory."""
    try:
        git_bin = check_git()
        resolved_cwd = Path(cwd).resolve()

        if not resolved_cwd.exists():
            return {"success": False, "output": "", "error": f"Path '{cwd}' does not exist."}

        result = subprocess.run(
            [git_bin] + args, cwd=str(resolved_cwd), capture_output=True, text=True, check=False
        )

        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
        }
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


def git_status(
    path: Annotated[str, "The path to the local git repository."] = ".",
) -> GitOperationResult:
    """
    Shows the working tree status.
    Use this to see which files are staged, unstaged, or untracked.

    Args:
        path: Absolute or relative path to the git repository.
    """
    return run_git_command(["status"], path)


def git_log(
    path: Annotated[str, "The path to the local git repository."] = ".",
    limit: Annotated[int, "The maximum number of commits to return."] = 5,
) -> GitOperationResult:
    """
    Shows the commit logs.
    Useful for understanding the history of changes in the repository.

    Args:
        path: Path to the git repository.
        limit: Number of recent commits to display.
    """
    return run_git_command(["log", f"-n {limit}", "--oneline"], path)


def git_diff(
    path: Annotated[str, "The path to the local git repository."],
    staged: Annotated[bool, "If True, show differences for files staged for commit."] = False,
) -> GitOperationResult:
    """
    Show changes between commits, commit and working tree, etc.
    Default behavior shows unstaged changes.

    Args:
        path: Path to the git repository.
        staged: Whether to view staged changes.
    """
    args = ["diff"]
    if staged:
        args.append("--staged")
    return run_git_command(args, path)


def git_add(
    path: Annotated[str, "The path to the local git repository."],
    files: Annotated[List[str], "A list of filenames or patterns to stage."],
) -> GitOperationResult:
    """
    Adds file contents to the staging index.

    Args:
        path: Path to the git repository.
        files: List of files to add. Use ['.'] to add all changes.
    """
    return run_git_command(["add"] + files, path)


def git_commit(
    path: Annotated[str, "The path to the local git repository."],
    message: Annotated[str, "The commit message describing the changes."],
) -> GitOperationResult:
    """
    Records changes to the repository.

    Args:
        path: Path to the git repository.
        message: The descriptive message for the commit.
    """
    if not message:
        return {"success": False, "output": "", "error": "Commit message cannot be empty."}
    return run_git_command(["commit", "-m", message], path)


def git_clone(
    url: Annotated[str, "The URL of the remote repository to clone."],
    path: Annotated[str, "The local directory path where the repo should be cloned."],
    branch: Annotated[Optional[str], "Optional branch name to clone."] = None,
) -> GitOperationResult:
    """
    Clones a repository into a new directory.

    Args:
        url: The git URL (HTTPS or SSH).
        path: The target local directory.
        branch: Specific branch to check out.
    """
    try:
        git_bin = check_git()
        # Resolve parent directory to ensure we can write there
        target_path = Path(path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        args = ["clone", url, str(target_path)]
        if branch:
            args += ["-b", branch]

        result = subprocess.run([git_bin] + args, capture_output=True, text=True, check=False)

        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
        }
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


def git_init(
    path: Annotated[str, "The directory to initialize as a git repository."],
) -> GitOperationResult:
    """
    Creates an empty Git repository or reinitializes an existing one.

    Args:
        path: The local directory path.
    """
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return run_git_command(["init"], path)
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


def git_checkout(
    path: Annotated[str, "The path to the local git repository."],
    target: Annotated[str, "The branch name or commit hash to switch to."],
    create_branch: Annotated[bool, "If True, creates a new branch (git checkout -b)."] = False,
) -> GitOperationResult:
    """
    Switches branches or restores working tree files.

    Args:
        path: Path to the git repository.
        target: The branch, tag, or commit.
        create_branch: Whether to create the branch if it doesn't exist.
    """
    args = ["checkout"]
    if create_branch:
        args.append("-b")
    args.append(target)
    return run_git_command(args, path)
