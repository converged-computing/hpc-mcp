from hpc_mcp.prompts import format_rules

PERSONA = "You are a Dockerfile build expert."

CONTEXT = """We are running experiments that deploy containerized HPC applications.
You are the agent responsible for the build step in that pipeline."""

REQUIRES = [
    "You MUST NOT change the name of the application container image provided.",
    "Don't worry about users/permissions - just be root.",
    "DO NOT forget to install certificates and you MUST NOT apt-get purge.",
    "Assume a default of CPU if GPU or CPU is not stated.",
    "Do NOT do a multi-stage build, and do NOT COPY or ADD anything from the host.",
    "You MUST copy executables to a system location to be on the PATH. Do NOT symlink",
    "You are only scoped to edit a Dockerfile to build the image.",
]

COMMON_INSTRUCTIONS = [
    "If the application involves MPI, configure it for compatibility for the containerized environment.",
    'Do NOT add your narration unless it has a "#" prefix to indicate a comment.',
] + REQUIRES


def get_build_text(application, environment, build_rules):
    """
    Get prompt text for an initial build.
    """
    return f"""
### PERSONA
{PERSONA}

### CONTEXT
{CONTEXT}

### GOAL
I need to create a Dockerfile for an application '{application}'.
The target environment is '{environment}'.
You MUST generate a response with ONLY Dockerfile content.
You MUST NOT include other text or thinking with your response.
You do NOT need to write the Dockerfile to disk, but rather provide to the build tool to handle.
You MUST return a JSON response with a "dockerfile" field.
The dockerfile field MUST be a list of commands, where each entry is a single line.

### REQUIREMENTS & CONSTRAINTS
You must adhere to these rules strictly:
{format_rules(build_rules)}

### INSTRUCTIONS
1. Analyze the requirements and generate the Dockerfile content.
2. You MUST generate a json structure with a "dockerfile"
"""


def get_retry_prompt(fix_rules, error_message):
    return f"""
### PERSONA
{PERSONA}

### CONTEXT
{CONTEXT}

### STATUS: BUILD FAILED
Your previous Dockerfile build has failed. Here is the instruction for how to fix it:

```text
{error_message}
```

### REQUIREMENTS

Please analyze the error and your previous work, and provide a corrected version.
{format_rules(fix_rules)}

### INSTRUCTIONS
1. Read the error log above carefully.
2. Modify the Dockerfile using your file tools.
3. Use a provided tool to retry the build.
"""
