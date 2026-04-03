"""
Tests for SQL Tool.
"""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from xagent.core.tools.core.sql_tool import (
    _get_connection_url,
    _row_to_dict,
    SQLPolicyDecision,
    execute_sql_query,
    get_database_type,
)


class TestGetConnectionUrl:
    """Test connection URL retrieval from environment variables."""

    def test_get_connection_url_success(self, monkeypatch):
        """Test successful URL retrieval."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///test.db")
        url = _get_connection_url("test")
        assert url.drivername == "sqlite"
        assert url.database == "test.db"

    def test_get_connection_url_case_insensitive(self, monkeypatch):
        """Test connection name is case-insensitive."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_ANALYTICS", "postgresql://localhost/db")
        url = _get_connection_url("analytics")
        assert url.drivername == "postgresql"

    def test_get_connection_url_not_found(self, monkeypatch):
        """Test error when connection not found."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///test.db")
        with pytest.raises(ValueError, match="Database connection 'missing' not found"):
            _get_connection_url("missing")

    def test_get_connection_url_no_databases(self, monkeypatch):
        """Test error when no databases configured."""
        # Clear any existing XAGENT_EXTERNAL_DB_* variables
        for key in list(os.environ.keys()):
            if key.startswith("XAGENT_EXTERNAL_DB_"):
                monkeypatch.delenv(key)
        with pytest.raises(ValueError, match="not found"):
            _get_connection_url("test")


class TestGetDatabaseType:
    """Test database type detection."""

    def test_get_database_type_sqlite(self, monkeypatch):
        """Test SQLite database type detection."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///test.db")
        db_type = get_database_type("test")
        assert db_type == "sqlite"

    def test_get_database_type_postgresql(self, monkeypatch):
        """Test PostgreSQL database type detection."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_ANALYTICS", "postgresql://localhost/db")
        db_type = get_database_type("analytics")
        assert db_type == "postgresql"

    def test_get_database_type_mysql(self, monkeypatch):
        """Test MySQL database type detection."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_PROD", "mysql+pymysql://localhost/prod")
        db_type = get_database_type("prod")
        assert db_type == "mysql"

    def test_get_database_type_not_found(self, monkeypatch):
        """Test error when connection not found."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///test.db")
        with pytest.raises(ValueError, match="not found"):
            get_database_type("missing")


class TestRowToDict:
    """Test SQLAlchemy Row to dict conversion."""

    def test_row_to_dict_basic(self):
        """Test basic row conversion."""
        mock_row = Mock()
        mock_row._mapping = {"id": 1, "name": "test"}
        result = _row_to_dict(mock_row)
        assert result == {"id": 1, "name": "test"}

    def test_row_to_dict_empty(self):
        """Test empty row conversion."""
        mock_row = Mock()
        mock_row._mapping = {}
        result = _row_to_dict(mock_row)
        assert result == {}


class TestExecuteSqlQuery:
    """Test SQL query execution."""

    def test_execute_sql_query_no_connection(self, monkeypatch):
        """Test error when connection not found."""
        # Clear any existing XAGENT_EXTERNAL_DB_* variables
        for key in list(os.environ.keys()):
            if key.startswith("XAGENT_EXTERNAL_DB_"):
                monkeypatch.delenv(key)
        # The function raises ValueError when connection not found
        with pytest.raises(ValueError, match="not found"):
            execute_sql_query("missing", "SELECT 1")

    @patch("xagent.core.tools.core.sql_tool.create_engine")
    def test_execute_sql_query_basic_select(self, mock_create_engine, monkeypatch):
        """Test basic SELECT query."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///:memory:")

        # Mock the engine and connection
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        # Mock result
        mock_result = MagicMock()
        mock_result.returns_rows = True
        mock_row = Mock()
        mock_row._mapping = {"id": 1, "name": "test"}
        mock_result.all.return_value = [mock_row]
        mock_conn.execute.return_value = mock_result

        result = execute_sql_query("test", "SELECT * FROM users")
        assert result["success"] is True
        assert result["row_count"] == 1
        assert len(result["rows"]) == 1
        assert result["rows"][0] == {"id": 1, "name": "test"}

    @patch("xagent.core.tools.core.sql_tool.create_engine")
    def test_execute_sql_query_insert(self, mock_create_engine, monkeypatch):
        """Test INSERT query."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///:memory:")

        # Mock the engine and connection
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        # Mock result for INSERT
        mock_result = MagicMock()
        mock_result.returns_rows = False
        mock_result.rowcount = 5
        mock_conn.execute.return_value = mock_result

        result = execute_sql_query("test", "INSERT INTO users VALUES (1, 'test')")
        assert result["success"] is True
        assert result["row_count"] == 5
        assert (
            result["message"]
            == "Query executed successfully on 'test', affected 5 row(s)"
        )

    @patch("xagent.core.tools.core.sql_tool.create_engine")
    def test_execute_sql_query_with_export_csv(
        self, mock_create_engine, monkeypatch, tmp_path
    ):
        """Test query with CSV export."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///:memory:")

        # Mock the engine and connection
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        # Create mock Row objects for fetchmany
        mock_row1 = Mock()
        mock_row1._mapping = {"id": 1, "name": "test1"}
        mock_row2 = Mock()
        mock_row2._mapping = {"id": 2, "name": "test2"}

        # Mock result
        mock_result = MagicMock()
        mock_result.keys.return_value = ["id", "name"]
        mock_result.fetchmany.side_effect = [
            [mock_row1, mock_row2],
            [],  # End of results
        ]
        mock_conn.execute.return_value = mock_result

        # Mock workspace
        mock_workspace = MagicMock()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_file = output_dir / "test.csv"
        mock_workspace.resolve_path.return_value = str(output_file)

        result = execute_sql_query(
            "test",
            "SELECT * FROM users",
            output_file="test.csv",
            workspace=mock_workspace,
        )
        assert result["success"] is True
        assert result["row_count"] == 2
        assert "exported" in result["message"].lower()

    @patch("xagent.core.tools.core.sql_tool.create_engine")
    def test_execute_sql_query_export_parquet_no_pyarrow(
        self, mock_create_engine, monkeypatch
    ):
        """Test Parquet export fails without pyarrow."""
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///:memory:")

        # Mock workspace
        mock_workspace = MagicMock()
        mock_workspace.resolve_path.return_value = "/tmp/test.parquet"

        # Mock pyarrow import to fail
        with patch.dict("sys.modules", {"pyarrow": None}):
            # The function should raise ImportError when trying to import pyarrow
            with pytest.raises(ImportError, match="pyarrow"):
                execute_sql_query(
                    "test",
                    "SELECT * FROM users",
                    output_file="test.parquet",
                    workspace=mock_workspace,
                )

    @patch("xagent.core.tools.core.sql_tool.create_engine")
    def test_execute_sql_query_does_not_execute_when_waiting_approval(
        self, mock_create_engine, monkeypatch
    ):
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///:memory:")

        mock_gateway = Mock()
        mock_gateway.evaluate.return_value = SQLPolicyDecision(
            decision="wait_approval",
            sql_fingerprint="fp_1",
            risk_level="high",
            risk_reasons=["write_statement"],
            approval_request_id=9,
            ledger_match_id=None,
            message="Approval required",
        )

        result = execute_sql_query(
            "test",
            "UPDATE users SET status = 'inactive' WHERE id = 1",
            policy_gateway=mock_gateway,
            policy_context={
                "task_id": 1,
                "plan_id": "plan_1",
                "step_id": "step_2",
                "environment": "prod",
                "tool_name": "execute_sql_query",
                "tool_payload": {
                    "query": "UPDATE users SET status = 'inactive' WHERE id = 1"
                },
                "requested_by": 1,
                "attempt_no": 1,
                "dag_snapshot_version": 1,
                "resume_token": "resume_1",
            },
        )

        assert result["success"] is False
        assert result["blocked"] is True
        assert result["decision"] == "wait_approval"
        mock_create_engine.assert_not_called()

    @patch("xagent.core.tools.core.sql_tool.create_engine")
    def test_execute_sql_query_uses_policy_gateway_before_execution(
        self, mock_create_engine, monkeypatch
    ):
        monkeypatch.setenv("XAGENT_EXTERNAL_DB_TEST", "sqlite:///:memory:")

        mock_gateway = Mock()
        mock_gateway.evaluate.return_value = SQLPolicyDecision(
            decision="allow_direct",
            sql_fingerprint="fp_1",
            risk_level="low",
            risk_reasons=[],
            approval_request_id=None,
            ledger_match_id=3,
            message="Approved by ledger",
        )

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        mock_result = MagicMock()
        mock_result.returns_rows = False
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result

        result = execute_sql_query(
            "test",
            "UPDATE users SET status = 'inactive' WHERE id = 1",
            policy_gateway=mock_gateway,
            policy_context={
                "task_id": 1,
                "plan_id": "plan_1",
                "step_id": "step_2",
                "environment": "prod",
                "tool_name": "execute_sql_query",
                "tool_payload": {
                    "query": "UPDATE users SET status = 'inactive' WHERE id = 1"
                },
                "requested_by": 1,
                "attempt_no": 1,
                "dag_snapshot_version": 1,
                "resume_token": "resume_1",
            },
        )

        assert result["success"] is True
        mock_gateway.evaluate.assert_called_once()
        mock_create_engine.assert_called_once()
