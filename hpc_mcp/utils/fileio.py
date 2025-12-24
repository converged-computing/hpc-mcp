import json
import os
import platform
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager

import yaml


def run_sync(coroutine):
    """
    Runs an async coroutine synchronously.
    Patches the loop if running inside IPython/Jupyter.

    Note that I'm not currently using this - keeping here if need.
    """
    import asyncio

    import nest_asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We aren't in async -> patch it
        nest_asyncio.apply(loop)
        return loop.run_until_complete(coroutine)
    else:
        # We are in standard Python script -> Standard run
        return asyncio.run(coroutine)


def get_local_cluster():
    """
    Guess the local cluster based on the hostname
    """
    return platform.node().split("-")[0]


def read_json(filename):
    """
    Read json from file
    """
    return json.loads(read_file(filename))


def write_json(obj, filename):
    with open(filename, "w") as fd:
        fd.write(json.dumps(obj, indent=4))


def load_jobspec(filename):
    """
    Load a jobspec. First try yaml and fall back to json
    """
    # It is already loaded!
    if isinstance(filename, dict):
        return filename
    if isinstance(filename, str) and not os.path.exists(filename):
        return yaml.safe_load(filename)
    try:
        return read_yaml(filename)
    except:
        return read_json(filename)


def read_file(filename):
    """
    Read in a file content
    """
    with open(filename, "r") as fd:
        content = fd.read()
    return content


def make_executable(path):
    """
    Adds execute permission to a file.
    """
    current_mode = os.stat(path).st_mode

    # Add execute permission for owner, group, and others
    new_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

    # Set the new permissions
    os.chmod(path, new_mode)


def recursive_find(base, pattern="[.]py"):
    """recursive find will yield python files in all directory levels
    below a base path.

    Arguments:
      - base (str) : the base directory to search
      - pattern: a pattern to match, defaults to *.py
    """
    for root, _, filenames in os.walk(base):
        for filename in filenames:
            filepath = os.path.join(root, filename)
            if not re.search(pattern, filepath):
                continue
            yield filepath


def get_tmpfile(tmpdir=None, prefix="", suffix=None):
    """
    Get a temporary file with an optional prefix.
    """
    # First priority for the base goes to the user requested.
    tmpdir = get_tmpdir(tmpdir)

    # If tmpdir is set, add to prefix
    if tmpdir:
        prefix = os.path.join(tmpdir, os.path.basename(prefix))

    fd, tmp_file = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(fd)

    return tmp_file


def get_tmpdir(tmpdir=None, prefix="", create=True):
    """
    Get a temporary directory for an operation.
    """
    tmpdir = tmpdir or tempfile.gettempdir()
    prefix = prefix or "jobspec"
    prefix = "%s.%s" % (prefix, next(tempfile._get_candidate_names()))
    tmpdir = os.path.join(tmpdir, prefix)

    if not os.path.exists(tmpdir) and create is True:
        os.mkdir(tmpdir)

    return tmpdir


def read_yaml(filename):
    """
    Read yaml from file
    """
    with open(filename, "r") as fd:
        content = yaml.safe_load(fd)
    return content


def write_file(content, filename):
    """
    Write content to file
    """
    with open(filename, "w") as fd:
        fd.write(content)


def write_yaml(obj, filename):
    """
    Read yaml to file
    """
    with open(filename, "w") as fd:
        yaml.dump(obj, fd)


@contextmanager
def workdir(dirname):
    """
    Provide context for a working directory, e.g.,

    with workdir(name):
       # do stuff
    """
    here = os.getcwd()
    os.chdir(dirname)
    try:
        yield
    finally:
        os.chdir(here)


def run_command(cmd, stream=False, check_output=False, return_code=0):
    """
    use subprocess to send a command to the terminal.

    If check_output is True, check against an expected return code.
    """
    stdout = subprocess.PIPE if not stream else None
    output = subprocess.Popen(cmd, stderr=subprocess.STDOUT, stdout=stdout, env=os.environ.copy())
    t = output.communicate()[0], output.returncode
    output = {"message": t[0], "return_code": t[1]}

    if isinstance(output["message"], bytes):
        output["message"] = output["message"].decode("utf-8")

    # Check the output and raise an error if not success
    if check_output and t[1] != return_code:
        if output["message"]:
            raise ValueError(output["message"].strip())
        else:
            raise ValueError(f"Failed execution, return code {t[1]}")
    return output
