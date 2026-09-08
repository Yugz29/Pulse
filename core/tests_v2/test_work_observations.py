"""Contradictions must survive projection, before any model or prompt."""
import json
from copy import deepcopy

from daemon_v2.work_observations import project_work_observations


def event(i, kind, **details):
    return {"id": i, "event_id": f"event-{i}", "type": kind,
            "occurred_at": f"2026-09-08T14:{i:02d}:00+00:00", "details": details}


def command(i, code, text="pytest", **details):
    return event(i, "terminal_finished", command=text, exit_code=code, cwd="/work/Pulse", **details)


def edit(i, change="modified", path="/work/Pulse/auth.py"):
    return event(i, "file_changed", path=path, event=change, workspace="/work/Pulse")


def latest(projection):
    refs = projection["last_observed"]["commands"]
    return [f for f in projection["timeline"] if f["ref"] in refs]


def test_failed_edit_passed_and_commit_preserve_observation_order():
    events = [command(1, 1), edit(4), command(8, 0),
              event(12, "git_commit", commit_hash="abc123", message="fix auth\n\nFull explanation", git_root="/work/Pulse")]
    result = project_work_observations(events)
    assert [f["kind"] for f in result["timeline"]] == ["command", "file", "command", "commit"]
    assert [f["exit_code"] for f in latest(result)] == [0]
    assert result["timeline"][-1]["message"].endswith("Full explanation")
    assert result["coverage"]["remote_push_state"] == "not_collected"
    assert result["sources"] == {f"o{i+1}": [e["event_id"]] for i, e in enumerate(events)}


def test_edit_does_not_invent_a_success():
    result = project_work_observations([command(1, 1), edit(4)])
    assert latest(result)[0]["exit_code"] == 1
    assert "resolved" not in json.dumps(result)


def test_repeated_cycles_and_independent_cwds():
    events = [command(i, code) for i, code in enumerate([1, 0, 1, 0], 1)]
    other = command(5, 1)
    other["details"]["cwd"] = "/work/Other"
    result = project_work_observations(events + [other])
    assert [f["exit_code"] for f in result["timeline"]] == [1, 0, 1, 0, 1]
    assert [f["exit_code"] for f in latest(result)] == [0, 1]


def test_compound_exit_is_not_each_tests_result():
    result = project_work_observations([command(1, 0, "pytest; echo done"), command(2, 1, "pytest && false")])
    assert all(not f["test_command"] and f["exit_scope"] == "whole_command" for f in result["timeline"])


def test_git_commit_does_not_invent_clean_status_or_push_success():
    events = [command(1, 0, "git status", git={"git_root": "/work/Pulse", "dirty": True, "branch": "main"}), edit(2),
              event(3, "git_commit", commit_hash="a" * 40, message="fix", git_root="/work/Pulse", branch="main"),
              command(4, 128, "git push")]
    result = project_work_observations(events)
    assert result["last_observed"]["git"]["/work/Pulse"] == {"dirty": "o1", "branch": "o3", "commit": "o3"}
    assert result["timeline"][-1]["git_action"] == "push"
    assert result["timeline"][-1]["exit_code"] == 128
    assert "push_succeeded" not in json.dumps(result)


def test_file_repetitions_keep_transitions_intervals_and_command_barriers():
    events = [edit(1, "created"), edit(2), edit(3), edit(4, "deleted"), edit(5, "created"), command(6, 0), edit(7)]
    result = project_work_observations(events)
    assert len(result["timeline"]) == 3
    changes = result["timeline"][0]["changes"]
    assert [c["event"] for c in changes] == ["created", "modified", "deleted", "created"]
    assert changes[1]["count"] == 2 and changes[1]["last_at"] == 120
    assert result["last_observed"]["files"] == ["o3"]
    assert result["sources"]["o1"] == [f"event-{i}" for i in range(1, 6)]


def test_deterministic_from_recorded_order_without_mutation():
    events = [edit(1), command(1, 1), edit(2)]
    events[1]["id"] = 4
    saved = deepcopy(events)
    assert project_work_observations(events) == project_work_observations(list(reversed(events)))
    assert events == saved


def test_absent_results_and_status_remain_absent():
    result = project_work_observations([event(1, "terminal_finished", command="pytest")])
    assert latest(result)[0]["exit_code"] is None
    assert result["last_observed"]["git"] == {}
    assert result["coverage"]["command_output"] == "not_collected"


def test_malformed_shell_quote_does_not_break_context():
    assert project_work_observations([command(1, 1, "git 'push")])["timeline"][0]["exit_code"] == 1


def test_historical_tool_noise_is_counted_without_losing_raw_provenance():
    events = [edit(1, path='/work/Pulse/.gitnexus/index.db'), edit(2)]
    result = project_work_observations(events)
    assert result['coverage']['omitted_events'] == {'file_noise': 1}
    assert [f['path'] for f in result['timeline']] == ['auth.py']
    assert len(events) == 2


def test_two_overlapping_agents_are_selected_by_observed_workspace(tmp_path):
    from test_context_snapshot import make_store, terminal, file_changed, agent_session, snapshot, PULSE, DEVNOTE
    store = make_store(tmp_path, terminal(-20, 'pytest'), file_changed(-15, 'auth.py'),
                       agent_session(-19, ended_minutes=-10, root=PULSE, first_prompt='Pulse request'),
                       agent_session(-18, ended_minutes=-9, root=DEVNOTE, first_prompt='Other request'))
    result = snapshot(store)
    assert result['last_agent_session']['workspace'] == PULSE
    assert 'Pulse request' in result['last_agent_session']['summary']
    assert result['last_agent_session']['event_id']


def test_summary_provenance_is_validated_without_rewriting_sources():
    import pytest
    from daemon_v2.ingest import _validate_observation_provenance, InvalidActivity
    value = {'observation_version': 1, 'observation_sources': {'o1': ['legacy-migrated:1'], 'app:1': ['event-app']}}
    saved = deepcopy(value)
    _validate_observation_provenance(value)
    assert value == saved
    for sources in ({'arbitrary free text': ['event']}, {'o1': ['TOKEN=audit-secret']}, {'o1': 'event'}, {'o1': []}):
        with pytest.raises(InvalidActivity):
            _validate_observation_provenance({**value, 'observation_sources': sources})


def test_mismatched_historical_workspace_is_unknown_instead_of_discarded():
    observed = edit(1, path='/work/Other/auth.py')
    result = project_work_observations([observed])
    assert result['timeline'][0]['path'] == '/work/Other/auth.py'
    assert result['timeline'][0]['workspace'] is None
    assert result['coverage']['omitted_events'] == {}
