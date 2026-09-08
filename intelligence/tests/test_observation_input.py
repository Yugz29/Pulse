"""Current observations, uncertainty and audit provenance cross the boundary."""
from copy import deepcopy
import json
from dataclasses import replace

import pytest
from conftest import REFERENCE, at, session_view, valid_output
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_input import build_model_input, serialize_input, input_paths, input_references
from pulse_intelligence.session_summary import build_event, parse_model_output, summarize_session
from pulse_intelligence.provider_summarizer import ProviderSummarizer, prompt_path_for
from pulse_intelligence.llm.fake import FakeProvider
from pulse_intelligence.summarizer import SummarizerError, FakeSummarizer


def observed_session():
    raw = session_view('aaaaaaaaaaaaaaaa')
    raw['workspace'] = '/work/Pulse'
    raw['observations'] = {
        'version': 1, 'timeline': [
            {'ref': 'o1', 'kind': 'command', 'command': 'pytest', 'exit_code': 1, 'at': 0},
            {'ref': 'o2', 'kind': 'file', 'path': 'auth.py', 'at': 180,
             'changes': [{'event': 'modified', 'first_at': 180, 'last_at': 180, 'count': 1}]},
            {'ref': 'o3', 'kind': 'command', 'command': 'pytest', 'exit_code': 0, 'at': 420}],
        'applications': [], 'last_observed': {'commands': ['o3'], 'files': ['o2'], 'git': {}},
        'sources': {'o1': ['source-failed'], 'o2': ['source-edit'], 'o3': ['source-passed']},
    }
    return SessionView(raw, REFERENCE.date())


def test_chronology_and_latest_result_reach_model_without_uuid_provenance():
    session = observed_session(); saved = deepcopy(session.raw)
    value = build_model_input(session, {}, references=True)
    text = serialize_input(value)
    assert 'source-failed' not in text and 'source_event_ids' not in text and 'sources' not in text
    assert value['session']['observations']['last_observed']['commands'] == ['o3']
    assert [f['ref'] for f in value['session']['observations']['timeline']] == ['o1', 'o2', 'o3']
    assert input_references(value).refs == frozenset({'o1', 'o2', 'o3'})
    assert input_paths(session) == {'auth.py'}
    assert session.raw == saved
    assert serialize_input(build_model_input(session, {}, references=True)) == text


def test_agent_workspace_is_checked_and_unknown_is_explicit():
    session = observed_session()
    agent = {'agent': 'codex', 'started_at': session.started_at.isoformat(),
             'ended_at': session.ended_at.isoformat(), 'workspace': '/work/Other', 'summary': 'Other request'}
    assert build_model_input(session, {'last_agent_session': agent}, references=True)['agent_session'] is None
    agent['workspace'] = '/work/Pulse/'
    assert build_model_input(session, {'last_agent_session': agent})['agent_session']['workspace_attribution'] == 'same_workspace'
    agent['workspace'] = None
    assert build_model_input(session, {'last_agent_session': agent})['agent_session']['workspace_attribution'] == 'unknown'


def test_old_snapshots_remain_readable_without_fabricated_order():
    old = SessionView(session_view('aaaaaaaaaaaaaaaa'), REFERENCE.date())
    value = build_model_input(old, {}, references=True)
    assert value['session']['chronology'] == 'unavailable_in_legacy_snapshot'
    assert 'last_observed' not in value['session']
    assert 'source_event_ids' not in serialize_input(value)


def test_old_prompt_cannot_silently_generate_with_new_contract():
    summarizer = ProviderSummarizer(FakeProvider(), 'fake/model', prompt_path_for('v3'))
    with pytest.raises(SummarizerError, match='v5'):
        summarizer.complete(serialize_input(build_model_input(observed_session(), {})))
    assert summarizer.provider.calls == []


def test_a_summary_persists_the_mapping_outside_its_input():
    session = observed_session(); visible = build_model_input(session, {}, references=True)
    output = json.loads(valid_output())
    output['reprise']['open'] = []
    output['structured']['central_files'] = ['auth.py']
    parsed = parse_model_output(json.dumps(output), input_paths(session), references=input_references(visible))
    event = build_event(session, parsed, prompt_version='v5', model_id='fake',
                        generated_at=REFERENCE, generation_ms=1, context_hash='a'*64, workspace='/work/Pulse')
    assert event['details']['observation_sources'] == session.raw['observations']['sources']
    assert event['details']['observation_version'] == 1
    assert event['details']['reconstruction_version'] == session.reconstruction_version


def test_generation_and_recovery_keep_provenance(fake_core, client, config, state):
    session = observed_session(); config = replace(config, prompt_version='v5')
    out = json.loads(valid_output()); out['reprise']['open'] = []; out['structured']['central_files'] = ['auth.py']
    model = FakeSummarizer(json.dumps(out), model_id=config.model_id)
    result = summarize_session(session, client=client, summarizer=model, config=config, state=state, now=REFERENCE)
    assert result.status == 'created'
    assert fake_core.posts[0]['details']['observation_sources'] == session.raw['observations']['sources']
    again = summarize_session(session, client=client, summarizer=model, config=config, state=state, now=REFERENCE)
    assert again.status == 'already_known'
    assert len(model.calls) == 1


def test_only_selected_annex_provenance_is_persisted_outside_prompt():
    from pulse_intelligence.session_input import input_provenance
    session = observed_session()
    agent = {'event_id': 'agent-source', 'workspace': '/work/Pulse', 'agent': 'codex',
             'started_at': session.started_at.isoformat(), 'ended_at': session.ended_at.isoformat(), 'summary': 'Request'}
    context = {'last_agent_session': agent}
    value = build_model_input(session, context, references=True)
    assert 'agent-source' not in serialize_input(value)
    assert input_provenance(session, context, value)['agent_request:0'] == ['agent-source']
    agent['workspace'] = '/work/Other'
    value = build_model_input(session, context, references=True)
    assert 'agent_request:0' not in input_provenance(session, context, value)


def test_human_commit_anchor_changes_spelling_without_changing_rules(tmp_path):
    from pulse_intelligence.evaluation import compare_run
    expected = tmp_path / 'expected'; expected.mkdir()
    rule = {'id': 's', 'open': [{'kind': 'observed', 'evidence': ['commit:abcdefg']}],
            'must_not': [{'text_matches': 'invented'}]}
    (expected / 's.json').write_text(json.dumps(rule))
    result = {'status': 'ok', 'open_items': [{'text': 'invented', 'kind': 'observed', 'evidence': ['o7']}],
              'commit_references': {'o7': 'commit:abcdefg'}}
    (tmp_path / 's.json').write_text(json.dumps(result))
    comparison = compare_run(tmp_path, expected)[0]
    assert len(comparison.matched) == 1 and len(comparison.forbidden) == 1 and not comparison.ok
    assert json.loads((tmp_path / 's.json').read_text()) == result
