"""Example tool module for lama_ole."""

__tool_readonly__ = True

import os
from tool_base import tool
from tools_security.validate_path import validate_path as _validate_path


@tool(description="Get the current weather for a city")
def get_weather(city: str) -> str:
    return f"Weather in {city}: 22°C, partly cloudy"


@tool(description="Calculate a mathematical expression")
def calculate(expression: str) -> str:
    import ast
    import operator

    allowed = {"abs": abs, "min": min, "max": max, "sum": sum}

    # Safe evaluation using ast to avoid arbitrary code execution.
    node = ast.parse(expression, mode="eval").body

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float)):
                return n.value
            raise ValueError("Unsupported constant")
        if isinstance(n, ast.Num):  # py3.7 compat
            return n.n
        if isinstance(n, ast.BinOp):
            left = _eval(n.left)
            right = _eval(n.right)
            ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
            }
            if type(n.op) not in ops:
                raise ValueError("Unsupported operator")
            return ops[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp):
            operand = _eval(n.operand)
            if isinstance(n.op, ast.USub):
                return -operand
            if isinstance(n.op, ast.UAdd):
                return +operand
            raise ValueError("Unsupported unary operator")
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in allowed:
                raise ValueError("Unsupported function")
            args = [_eval(a) for a in n.args]
            return allowed[n.func.id](*args)
        raise ValueError("Unsupported expression")

    result = _eval(node)
    return str(result)


@tool(description="Read the contents of a file")
def read_file(path: str) -> str:
    safety_error = _validate_path(path)
    if safety_error:
        return {"status": "error", "message": [safety_error]}

    with open(path, "rb") as f:
        raw_content = f.read()

    # Entropy check: reject binary / random content before it reaches the LLM
    from security.entropychecker import EntropyChecker

    result = EntropyChecker().feed(raw_content)
    if result.is_suspicious:
        return {
            "status": "error",
            "message": [f"File rejected by entropy check: {result.reason}"],
        }

    return {"status": "success", "data": raw_content.decode("utf-8", errors="replace")}
