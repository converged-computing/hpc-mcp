import json
import subprocess
from typing import Any, Dict, Optional

from rich import print

from hpc_mcp.logger import logger


class Result:
    """
    Standardized return object for MCP tools.
    Handles formatting output, errors, and metadata for the LLM.
    """

    def __init__(
        self, content: Any = None, returncode: int = 0, stderr: str = "", metadata: Dict = None
    ):

        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr
        self.metadata = metadata or {}
        self.parse(content)

    def parse(self, content):
        """
        Parse content into the unified interface.
        """
        # subprocess result
        if isinstance(content, subprocess.CompletedProcess):
            self.returncode = content.returncode
            self.stdout = self._decode(content.stdout)
            self.stderr = self._decode(content.stderr)

        # handle exception
        elif isinstance(content, Exception):
            self.returncode = 1
            self.stderr = str(content)

        # handle string / dict
        elif isinstance(content, (str, dict, list)):
            if isinstance(content, (dict, list)):
                self.stdout = json.dumps(content, indent=2)
            else:
                self.stdout = str(content)

        # empty init (manual setting later)
        else:
            self.stdout = ""

    def _decode(self, val):
        """
        Safe decoding of bytes or string.
        """
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
        return str(val)

    @property
    def is_success(self):
        return self.returncode == 0

    def render(self) -> str:
        """
        Renders the result into a formatted string for the LLM.
        """
        status = "SUCCESS" if self.is_success else "FAILURE"
        logfunc = logger.success if self.is_success else logger.failure
        icon = "✅" if self.is_success else "❌"
        sections = [f"{icon} STATUS: {status} (Exit Code {self.returncode})"]

        if self.stdout.strip():
            # Use code blocks for clear separation
            sections.append(f"--- STDOUT ---\n```text\n{self.stdout.strip()}\n```")

        if self.stderr.strip():
            sections.append(f"--- STDERR ---\n```text\n{self.stderr.strip()}\n```")

        if self.metadata:
            sections.append(
                f"--- METADATA ---\n```json\n{json.dumps(self.metadata, indent=2)}\n```"
            )

        if not self.is_success:
            sections.append("HINT: Analyze the STDERR output above to determine the fix.")

        result = "\n\n".join(sections)
        logfunc(result)
        return result

    def to_json(self) -> str:
        """
        Returns raw JSON for machine-readable only.
        """
        return json.dumps(
            {
                "returncode": self.returncode,
                "stdout": self.stdout,
                "stderr": self.stderr,
                "metadata": self.metadata,
            }
        )
