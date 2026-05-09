from daemon.core.test_result_parser import parse_test_result


def test_parse_pytest_failed_and_passed_counts():
    result = parse_test_result(
        command="pytest",
        terminal_action_category="testing",
        success=False,
        exit_code=1,
        output_summary="2 failed, 64 passed in 12.3s",
    )

    assert result == {
        "framework": "pytest",
        "success": False,
        "exit_code": 1,
        "failed_count": 2,
        "passed_count": 64,
        "summary": "2 failed, 64 passed",
    }


def test_parse_pytest_passed_count():
    result = parse_test_result(
        command="python -m pytest",
        terminal_action_category="testing",
        success=True,
        exit_code=0,
        output_summary="66 passed in 8.4s",
    )

    assert result["framework"] == "pytest"
    assert result["passed_count"] == 66
    assert result["summary"] == "66 passed"


def test_parse_pytest_errors_failures_passed_and_skipped():
    result = parse_test_result(
        command="pytest tests/core/test_signal_scorer.py",
        terminal_action_category="testing",
        success=False,
        exit_code=1,
        output_summary="1 error, 3 failed, 20 passed, 2 skipped in 5.1s",
    )

    assert result["error_count"] == 1
    assert result["failed_count"] == 3
    assert result["passed_count"] == 20
    assert result["skipped_count"] == 2
    assert result["summary"] == "3 failed, 1 error, 2 skipped, 20 passed"


def test_parse_pytest_target_from_command():
    result = parse_test_result(
        command="python -m pytest -q tests/core/test_signal_scorer.py",
        terminal_action_category="testing",
        success=True,
        exit_code=0,
        output_summary="66 passed",
    )

    assert result["target"] == "tests/core/test_signal_scorer.py"


def test_parse_non_testing_command_returns_none():
    assert parse_test_result(
        command="pytest",
        terminal_action_category="inspection",
        success=True,
        exit_code=0,
        output_summary="66 passed",
    ) is None


def test_parse_npm_test_minimal_result():
    result = parse_test_result(
        command="npm test",
        terminal_action_category="testing",
        success=False,
        exit_code=1,
        output_summary="Test failed",
    )

    assert result == {
        "framework": "npm",
        "success": False,
        "exit_code": 1,
    }


def test_parse_vitest_minimal_result():
    result = parse_test_result(
        command="npm run test",
        terminal_action_category="testing",
        success=True,
        exit_code=0,
        output_summary="vitest 64 passed",
    )

    assert result["framework"] == "vitest"
    assert result["success"] is True
