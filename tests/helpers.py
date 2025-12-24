import ast
import json


def load_jobspec(result):
    """
    Load a jobspec from the tool response.
    """
    # The tool returns a JSON string, so we parse it
    data = json.loads(result.content[0].text)
    jobspec = data.get("jobspec")
    if isinstance(jobspec, str):
        try:
            jobspec = json.loads(jobspec)
        except json.JSONDecodeError:
            jobspec = ast.literal_eval(jobspec)

    return data, jobspec
