"""Tests for tool_runner.py helper functions and main()."""

import argparse
import base64
import json
from typing import Any, Mapping
from unittest.mock import patch

import cloudpickle
import pytest

from xagent.core.tools.adapters.vibe.sandboxed_tool.tool_runner import (
    _execute_from_spec,
    _load_args,
    _load_execution_spec,
    _load_init_params,
    _load_tool_class,
    _run_method,
    _run_tool,
    _validate_spec,
    main,
)


class _FakeTool:
    """Minimal fake tool for testing tool_runner."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def run_json_sync(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {"echo": args.get("msg", "")}

    async def run_json_async(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {"echo": args.get("msg", "")}


class _FakeMethodOwner:
    """Simple method owner used to test method-based execution specs."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def say(self, msg: str) -> dict[str, Any]:
        return {"echo": f"{self.prefix}{msg}"}


class TestLoadArgs:
    """Tests for _load_args()."""

    def test_roundtrip(self):
        """Base64-encoded JSON should decode back to original dict."""
        original = {"msg": "hello", "count": 42}
        b64 = base64.b64encode(json.dumps(original).encode()).decode()
        assert _load_args(b64) == original


class TestLoadInitParams:
    """Tests for _load_init_params()."""

    def test_none_returns_empty(self):
        """None input should return empty dict."""
        assert _load_init_params(None) == {}

    def test_roundtrip(self):
        """Cloudpickle-serialized params should deserialize correctly."""
        params = {"key": "value"}
        b64 = base64.b64encode(cloudpickle.dumps(params)).decode()
        assert _load_init_params(b64) == params


class TestLoadToolClass:
    """Tests for _load_tool_class()."""

    def test_valid_import(self):
        """Valid import path should resolve to the correct class."""
        cls = _load_tool_class(
            "tests.core.tools.adapters.sandboxed_tool.test_tool_runner:_FakeTool"
        )
        assert cls.__name__ == "_FakeTool"

    def test_invalid_module(self):
        """Non-existent module should raise ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            _load_tool_class("no.such.module:Cls")


class TestLoadExecutionSpec:
    def test_from_tool_execution_spec_b64(self):
        """Tool execution spec load."""
        execution_spec_b64 = base64.b64encode(
            json.dumps({"kind": "tool", "tool_class": "a.b:Tool"}).encode()
        ).decode()
        parsed = argparse.Namespace(execution_spec_b64=execution_spec_b64)
        assert _load_execution_spec(parsed) == {
            "kind": "tool",
            "tool_class": "a.b:Tool",
        }

    def test_from_method_execution_spec_b64(self):
        """Method execution spec load."""
        execution_spec_b64 = base64.b64encode(
            json.dumps(
                {"kind": "method", "tool_class": "a.b:Tool", "method_name": "run"}
            ).encode()
        ).decode()
        parsed = argparse.Namespace(execution_spec_b64=execution_spec_b64)
        assert _load_execution_spec(parsed) == {
            "kind": "method",
            "tool_class": "a.b:Tool",
            "method_name": "run",
        }


class TestRunTool:
    """Tests for _run_tool()."""

    def test_sync(self):
        """Sync tool should return result directly."""
        tool = _FakeTool()
        assert _run_tool(tool, {"msg": "hi"}) == {"echo": "hi"}


class TestRunMethod:
    def test_sync(self):
        """Sync bound methods should receive decoded kwargs and return output."""
        owner = _FakeMethodOwner(prefix="hello ")
        assert _run_method(owner.say, {"msg": "world"}) == {"echo": "hello world"}


class TestExecuteFromSpec:
    def test_tool_spec(self):
        """Tool specs should reconstruct the class and call run_json_*."""
        spec = {
            "kind": "tool",
            "tool_class": "tests.core.tools.adapters.sandboxed_tool.test_tool_runner:_FakeTool",
        }
        result = _execute_from_spec(spec, {}, {"msg": "ok"})
        assert result == {"echo": "ok"}

    def test_method_spec(self):
        """Method specs should reconstruct the class and call the target method."""
        spec = {
            "kind": "method",
            "tool_class": (
                "tests.core.tools.adapters.sandboxed_tool.test_tool_runner:"
                "_FakeMethodOwner"
            ),
            "method_name": "say",
        }
        result = _execute_from_spec(spec, {"prefix": "hi "}, {"msg": "there"})
        assert result == {"echo": "hi there"}


class TestValidateSpec:
    """Tests for _validate_spec()."""

    def test_unsupported_kind(self):
        with pytest.raises(ValueError, match="Unsupported execution kind"):
            _validate_spec({"kind": "unknown", "tool_class": "a:B"})

    def test_missing_kind(self):
        with pytest.raises(ValueError, match="Unsupported execution kind"):
            _validate_spec({"tool_class": "a:B"})

    def test_missing_tool_class(self):
        with pytest.raises(ValueError, match="missing required key 'tool_class'"):
            _validate_spec({"kind": "tool"})

    def test_method_missing_method_name(self):
        with pytest.raises(ValueError, match="missing required key 'method_name'"):
            _validate_spec({"kind": "method", "tool_class": "a:B"})


class TestMain:
    """Tests for main() entrypoint."""

    def test_happy_path(self, tmp_path):
        """Successful execution should write result JSON to file."""
        result_file = str(tmp_path / "result.json")
        args_b64 = base64.b64encode(json.dumps({"msg": "ok"}).encode()).decode()
        execution_spec = {
            "kind": "tool",
            "tool_class": (
                "tests.core.tools.adapters.sandboxed_tool.test_tool_runner:_FakeTool"
            ),
        }
        execution_spec_b64 = base64.b64encode(
            json.dumps(execution_spec).encode()
        ).decode()
        argv = [
            "--execution-spec-b64",
            execution_spec_b64,
            "--args-b64",
            args_b64,
            "--result-file",
            result_file,
        ]
        with patch("sys.argv", ["tool_runner"] + argv):
            main()
        result = json.loads((tmp_path / "result.json").read_text())
        assert result == {"echo": "ok"}

    def test_bad_module_raises(self, tmp_path):
        """Invalid tool class should raise as Sandbox config error."""
        result_file = str(tmp_path / "result.json")
        args_b64 = base64.b64encode(b"{}").decode()
        execution_spec_b64 = base64.b64encode(
            json.dumps({"kind": "tool", "tool_class": "no.such.module:Cls"}).encode()
        ).decode()
        argv = [
            "--execution-spec-b64",
            execution_spec_b64,
            "--args-b64",
            args_b64,
            "--result-file",
            result_file,
        ]
        with patch("sys.argv", ["tool_runner"] + argv):
            with pytest.raises(ModuleNotFoundError):
                main()

    def test_method_happy_path(self, tmp_path):
        """Method execution should round-trip through the CLI entrypoint."""
        result_file = str(tmp_path / "result.json")
        args_b64 = base64.b64encode(json.dumps({"msg": "tool"}).encode()).decode()
        init_params_b64 = base64.b64encode(
            cloudpickle.dumps({"prefix": "from "})
        ).decode()
        execution_spec_b64 = base64.b64encode(
            json.dumps(
                {
                    "kind": "method",
                    "tool_class": (
                        "tests.core.tools.adapters.sandboxed_tool.test_tool_runner:"
                        "_FakeMethodOwner"
                    ),
                    "method_name": "say",
                }
            ).encode()
        ).decode()
        argv = [
            "--execution-spec-b64",
            execution_spec_b64,
            "--args-b64",
            args_b64,
            "--result-file",
            result_file,
            "--init-params-b64",
            init_params_b64,
        ]
        with patch("sys.argv", ["tool_runner"] + argv):
            main()
        result = json.loads((tmp_path / "result.json").read_text())
        assert result == {"echo": "from tool"}
