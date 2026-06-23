"""Development tools for lama_ole — filesystem, code, and git operations."""

import base64
import os
import re
import glob as glob_mod
import subprocess
import py_compile
from pathlib import Path
from typing import Optional

from tool_base import tool



@tool(description="Read the contents of a file as base64")
def read_file_as_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode( f.read())

# crashes
# @tool(description="Read the contents of a file binary")
# def read_file_binary(path: str) -> str:
#     with open(path, "rb") as f:
#         return f.read()

