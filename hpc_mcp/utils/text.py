import os
import re


def format_rules(rules):
    return "\n".join([f"- {r}" for r in rules])


def envar_get_boolean(name):
    """
    Sniff the environment for a boolean value
    """
    value = os.environ.get(name)
    if not value:
        return False
    if value is not None and value.lower() in ["true", "t", "y", "yes", "1"]:
        return True
    if value is not None and value.lower() in ["false", "f", "n", "no", "0"]:
        return False
    return False


def envar_get_integer(name):
    """
    Sniff the environment for an integer value
    """
    value = os.environ.get(name)
    if value is None:
        return value
    if value.isdigit():
        return int(value)
    return None


def get_code_block(content, code_type):
    """
    Parse a code block from the response
    """
    pattern = f"```(?:{code_type})?\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    if content.startswith(f"```{code_type}"):
        content = content[len(f"```{code_type}") :]
    if content.startswith("```"):
        content = content[len("```") :]
    if content.endswith("```"):
        content = content[: -len("```")]
    return content.strip()
