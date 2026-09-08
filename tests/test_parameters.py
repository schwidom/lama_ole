import io
import os
import sys
import pytest

from parameters import (
    PARAMETERS,
    format_bash_c_quote,
    parse_cli_explicit_params,
    process_inspection_flags,
)


def test_format_bash_c_quote_plain():
    assert format_bash_c_quote("hello") == "hello"
    assert format_bash_c_quote("100000") == "100000"


def test_format_bash_c_quote_spaces_and_quotes():
    assert format_bash_c_quote("hello world") == '"hello world"'
    assert format_bash_c_quote('hello "world"') == '"hello \\"world\\""'


def test_format_bash_c_quote_special_characters():
    assert format_bash_c_quote("line1\nline2") == "$'line1\\nline2'"
    assert format_bash_c_quote("tab\tseparated") == "$'tab\\tseparated'"
    assert format_bash_c_quote("cr\rreturn") == "$'cr\\rreturn'"


def test_parse_cli_explicit_params():
    argv = ["--model", "gemma4:26b", "-t", "--temperature", "0.7", "--show-config", "--as-parameters"]
    parsed = parse_cli_explicit_params(argv)
    assert parsed.get("model") == "gemma4:26b"
    assert parsed.get("thinking") is True
    assert parsed.get("temperature") == 0.7
    assert "show-config" not in parsed


def test_parse_cli_explicit_params_store_true_long_flag():
    assert parse_cli_explicit_params(["--list"]) == {"list": True}
    assert parse_cli_explicit_params(["-l"]) == {"list": True}
    assert parse_cli_explicit_params(["--help-tools"]) == {"help_tools": True}
    assert parse_cli_explicit_params(["--stdin"]) == {"stdin": True}


def test_parse_cli_explicit_params_boolean_optional_negation():
    assert parse_cli_explicit_params(["--thinking"]) == {"thinking": True}
    assert parse_cli_explicit_params(["--no-thinking"]) == {"thinking": False}


def _cli_module():
    from lama_ole import lama_ole as cli_module
    return cli_module


def test_version_flag_standard_help_text():
    parser = _cli_module().build_parser()
    version_action = next(a for a in parser._actions if a.dest == "version")
    assert version_action.version == "0.0.65"
    assert version_action.help == "show program's version number and exit"


def test_cli_module_exports_get_tool_modules_info():
    assert hasattr(_cli_module(), "get_tool_modules_info")


def test_inspection_as_parameters(capsys):
    argv = ["--show-parameters", "--as-parameters", "--model", "gemma4:26b", "--temperature", "0.7"]
    initial_env = {}
    config_dict = {}

    res = process_inspection_flags(argv, config_dict, initial_env)
    assert res is True

    captured = capsys.readouterr().out
    assert '--model "gemma4:26b"' in captured or '--model gemma4:26b' in captured
    assert "--temperature 0.7" in captured


def test_inspection_as_environment(capsys):
    argv = ["--show-parameters", "--as-environment", "--model", "gemma4:26b", "-t"]
    initial_env = {}
    config_dict = {}

    res = process_inspection_flags(argv, config_dict, initial_env)
    assert res is True

    captured = capsys.readouterr().out
    assert 'export LAMA_OLE_MODEL="gemma4:26b"' in captured or 'export LAMA_OLE_MODEL=gemma4:26b' in captured
    assert "export LAMA_OLE_THINKING=true" in captured


def test_inspection_as_natural(capsys):
    argv = ["--show-environment", "--show-parameters", "--as-natural", "--model", "gemma4:26b"]
    initial_env = {"LAMA_OLE_NUM_CTX": "100000"}
    config_dict = {}

    res = process_inspection_flags(argv, config_dict, initial_env)
    assert res is True

    captured = capsys.readouterr().out
    assert '--model "gemma4:26b"' in captured or '--model gemma4:26b' in captured
    assert "LAMA_OLE_NUM_CTX=100000" in captured


def test_overwritten_comments(capsys):
    argv = ["--show-parameters", "--as-parameters", "--model", "winning_model"]
    initial_env = {"LAMA_OLE_MODEL": "env_model"}
    config_dict = {"LAMA_OLE_MODEL": "config_model"}

    res = process_inspection_flags(argv, config_dict, initial_env)
    assert res is True

    captured = capsys.readouterr().out
    assert 'winning_model' in captured
    assert '# (overrides environment: "env_model", config: "config_model")' in captured


def test_releasing_selectors_between_as_flags(capsys):
    argv = [
        "--show-environment",
        "--as-environment",
        "--show-parameters",
        "--as-parameters",
        "--model",
        "cli_model",
    ]
    initial_env = {"LAMA_OLE_NUM_CTX": "32768"}
    config_dict = {}

    res = process_inspection_flags(argv, config_dict, initial_env)
    assert res is True

    captured = capsys.readouterr().out
    # First section should have env
    assert "export LAMA_OLE_NUM_CTX=32768" in captured
    # Second section should have parameter
    assert '--model "cli_model"' in captured or '--model cli_model' in captured


def test_nonconfig_selector_support(capsys):
    argv = ["--show-config", "show-nonconfig", "--show-parameters", "--as-parameters", "--model", "m1"]
    initial_env = {}
    config_dict = {"LAMA_OLE_MODEL": "m2"}

    res = process_inspection_flags(argv, config_dict, initial_env)
    assert res is True

    captured = capsys.readouterr().out
    # Should show parameters because show-nonconfig discarded config
    assert "m1" in captured
