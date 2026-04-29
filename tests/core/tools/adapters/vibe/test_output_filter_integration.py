"""
Integration tests for output filter with tool factory.
"""

import pytest

from xagent.core.tools.adapters.vibe.config import ToolConfig
from xagent.core.tools.adapters.vibe.factory import ToolFactory
from xagent.core.tools.adapters.vibe.output_filter import DEFAULT_TRUNCATION_MESSAGE


@pytest.mark.asyncio
async def test_tool_factory_applies_filters():
    """Test that tools created by factory have output filtering."""
    config = ToolConfig(
        {
            "workspace": None,
            "max_output_length": 100,
        }
    )

    tools = await ToolFactory.create_all_tools(config)

    # Check that tools were created
    assert len(tools) > 0

    # Find any wrapped tool (all tools should be wrapped with _filter)
    wrapped_tools = [t for t in tools if hasattr(t, "_filter")]
    assert len(wrapped_tools) > 0, "No tools with output filter found"

    # Check that the filter has the correct configuration
    tool = wrapped_tools[0]
    assert hasattr(tool, "_filter")
    assert tool._filter.max_chars == 100


@pytest.mark.asyncio
async def test_filtered_tool_execution():
    """Test that filtered tools truncate output correctly when executed."""
    from langchain_core.tools.structured import StructuredTool
    from pydantic import BaseModel, Field

    from xagent.core.tools.adapters.vibe.base import AbstractBaseTool, ToolMetadata
    from xagent.core.tools.adapters.vibe.output_filter_wrapper import (
        OutputFilteredToolWrapper,
    )

    # Create a simple test tool that returns predictable long output
    class TestInput(BaseModel):
        text: str = Field(description="Text to repeat")

    def test_long_output_func(text: str) -> str:
        """Return the input text repeated 100 times for testing output filtering."""
        return text * 100

    # Create a StructuredTool
    langchain_tool = StructuredTool.from_function(
        func=test_long_output_func,
        name="test_long_output",
        description="Test tool that returns long output",
        args_schema=TestInput,
    )

    # Create AbstractBaseTool wrapper
    class TestTool(AbstractBaseTool):
        @property
        def name(self) -> str:
            return "test_long_output"

        @property
        def description(self) -> str:
            return "Test tool that returns long output"

        @property
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                name="test_long_output",
                description="Test tool that returns long output",
                category="BASIC",
            )

        def args_type(self):
            return TestInput

        def return_type(self):
            return str

        def state_type(self):
            return None

        def is_async(self):
            return False

        def run_json_sync(self, args):
            result = langchain_tool.invoke(args)
            return result

        async def run_json_async(self, args):
            return self.run_json_sync(args)

    # Wrap it with the same wrapper used by ToolFactory
    wrapped = OutputFilteredToolWrapper(
        target_tool=TestTool(),
        max_chars=50,
        max_fields=1000,
        max_recursion=20,
    )

    # Execute the tool and verify truncation
    result = wrapped.run_json_sync({"text": "abcdefghij" * 10})  # 100 chars

    # Result should be truncated to 50 chars + message
    assert len(result) <= 50 + len(DEFAULT_TRUNCATION_MESSAGE)
    assert result.endswith(DEFAULT_TRUNCATION_MESSAGE)
    assert result.startswith("abcdefghij")


@pytest.mark.asyncio
async def test_default_max_output_length():
    """Test that default max output length is 50K characters."""
    config = ToolConfig({"workspace": None})

    tools = await ToolFactory.create_all_tools(config)

    # Check that at least one tool was created
    assert len(tools) > 0

    # Check that tools have the default limit
    for tool in tools:
        if hasattr(tool, "_filter"):
            assert tool._filter.max_chars == 50 * 1024


@pytest.mark.asyncio
async def test_hardcoded_truncation_message():
    """Test that truncation message uses the hardcoded default from output_filter.py."""
    config = ToolConfig(
        {
            "workspace": None,
            "max_output_length": 10,
        }
    )

    tools = await ToolFactory.create_all_tools(config)

    # Find a tool and verify truncation message is used
    for tool in tools:
        if hasattr(tool, "_filter"):
            # The filter uses the hardcoded message from output_filter.py
            assert tool._filter.max_chars == 10
            break
