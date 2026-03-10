from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from xagent.web.api.websocket import handle_build_preview_execution
from xagent.web.models.model import Model as DBModel
from xagent.web.models.user import User


@pytest.mark.asyncio
async def test_handle_build_preview_execution_empty_tool_categories():
    """
    Test that handle_build_preview_execution does not raise UnboundLocalError
    when tool_categories is empty.
    """
    # Arrange
    mock_websocket = AsyncMock()
    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.is_admin = False

    message_data = {
        "instructions": "test instructions",
        "execution_mode": "graph",
        "models": {
            "general": 1,
        },
        "tool_categories": [],  # Empty list to trigger the potential issue
        "message": "test message",
    }

    # Mock DB Session
    mock_db = MagicMock(spec=Session)

    # Mock DB query results for models
    mock_model = MagicMock(spec=DBModel)
    mock_model.model_id = "test-model-id"

    # Mock query().filter().first() chain
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_filter
    mock_filter.first.return_value = mock_model

    # Mock dependencies
    with (
        patch("xagent.web.models.database.get_db", return_value=iter([mock_db])),
        patch("xagent.web.services.llm_utils.UserAwareModelStorage") as MockStorage,
        patch("xagent.core.agent.service.AgentService") as MockAgentService,
        patch("xagent.web.api.websocket.WebToolConfig") as MockWebToolConfig,
        patch("xagent.core.agent.trace.Tracer"),
        patch("xagent.core.memory.in_memory.InMemoryMemoryStore"),
    ):
        mock_storage_instance = MockStorage.return_value
        mock_storage_instance.get_llm_by_name_with_access.return_value = MagicMock()

        mock_agent_service = MockAgentService.return_value
        mock_agent_service.execute_task = AsyncMock(
            return_value={"output": "success", "status": "completed"}
        )

        # Act
        try:
            await handle_build_preview_execution(
                mock_websocket, message_data, mock_user
            )
        except UnboundLocalError as e:
            pytest.fail(f"UnboundLocalError raised: {e}")
        except Exception as e:
            # If other errors occur, we should check if they are related to our test setup
            # but getting past the UnboundLocalError is the main goal.
            # However, for a good test, it should run successfully.
            # Let's see if we can make it run successfully.
            # If we mock everything, it should be fine.
            pytest.fail(f"Unexpected error raised: {e}")

        # Assert
        # Verify WebToolConfig was called (this is where MinimalRequest is used)
        assert MockWebToolConfig.called
