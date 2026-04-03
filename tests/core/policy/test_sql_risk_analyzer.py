from xagent.core.policy.sql_risk_analyzer import SQLRiskAnalyzer


def test_select_is_low_risk():
    context = SQLRiskAnalyzer().analyze(
        datasource_id="ds_1",
        environment="prod",
        sql="SELECT * FROM users WHERE id = 1",
    )

    assert context.operation_type == "select"
    assert context.risk_level == "low"
    assert context.requires_approval is False


def test_delete_without_where_is_critical():
    context = SQLRiskAnalyzer().analyze(
        datasource_id="ds_1",
        environment="prod",
        sql="DELETE FROM users",
    )

    assert context.operation_type == "delete"
    assert context.risk_level == "critical"
    assert "delete_without_where" in context.risk_reasons
    assert context.requires_approval is True


def test_sql_fingerprint_is_parameterized():
    analyzer = SQLRiskAnalyzer()
    left = analyzer.analyze(
        "ds_1", "prod", "UPDATE users SET status = 'x' WHERE id = 1"
    )
    right = analyzer.analyze(
        "ds_1", "prod", "UPDATE users SET status = 'y' WHERE id = 2"
    )

    assert left.sql_fingerprint == right.sql_fingerprint
    assert left.sql_normalized == right.sql_normalized


def test_update_with_where_is_high_risk():
    context = SQLRiskAnalyzer().analyze(
        datasource_id="ds_1",
        environment="prod",
        sql="UPDATE users SET status = 'inactive' WHERE id = 99",
    )

    assert context.operation_type == "update"
    assert context.risk_level == "high"
    assert context.requires_approval is True

