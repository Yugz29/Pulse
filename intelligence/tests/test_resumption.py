"""Observation scope and positive evidence, not natural-language truth tests."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence.resumption import command_outcomes
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_input import build_model_input, input_paths, input_references, input_provenance
from pulse_intelligence.session_summary import InvalidModelOutput, parse_model_output, summarize_session
from pulse_intelligence.summarizer import FakeSummarizer


def command(ref, code, at, *, cwd='/work/Pulse', start=None):
    return dict(ref=ref, kind='command', command='pytest', cwd=cwd, at=at,
                started_at=at if start is None else start, exit_code=code)


def entry(facts):
    raw = session_view('aaaaaaaaaaaaaaaa')
    raw['workspace'] = '/work/Pulse'
    raw['observations'] = dict(version=1, timeline=facts, applications=[],
                               sources={f['ref']:['event-'+f['ref']] for f in facts})
    return SessionView(raw, REFERENCE.date())


def parse_items(session, items, context=None):
    model_input = build_model_input(session, context or {}, references=True)
    output = json.loads(valid_output()); output['reprise']['open'] = items
    output['structured']['central_files'] = []
    return parse_model_output(json.dumps(output), input_paths(session), references=input_references(model_input))


@pytest.mark.parametrize('codes,status,last', [
    ([1,0], 'resolved_observed','o2'), ([1], 'unresolved_observed','o1'),
    ([1,0,1,0], 'resolved_observed','o4'), ([1,0,1], 'unresolved_observed','o3'),
    ([1,None], 'unknown','o2'), ([1,130], 'unknown','o2'),
])
def test_last_result_has_a_bounded_observation_status(codes,status,last):
    facts=[command(f'o{i+1}',code,i*10) for i,code in enumerate(codes)]
    saved=deepcopy(facts); rows=command_outcomes(facts)
    assert rows[0]['status']==status and rows[0]['last']==last
    assert facts==saved and command_outcomes(facts)==rows


def test_overlapping_runs_and_unknown_or_distinct_cwd_do_not_prove_resolution():
    assert command_outcomes([command('o1',1,10),command('o2',0,20,start=5)])[0]['status']=='unknown'
    assert command_outcomes([command('o1',1,10),command('o2',0,20,cwd='/other')])[0]['status']=='unresolved_observed'
    assert command_outcomes([command('o1',1,10,cwd=None),command('o2',0,20,cwd=None)])[0]['status']=='unresolved_observed'


def test_structural_validation_rejects_resolved_or_nonlast_failure():
    item=dict(text='An arbitrary sentence, no lexical match needed.',kind='command_failure',evidence=['o1'])
    with pytest.raises(InvalidModelOutput,match='dernier échec'):
        parse_items(entry([command('o1',1,0),command('o2',0,10)]),[item])
    with pytest.raises(InvalidModelOutput,match='dernier échec'):
        parse_items(entry([command('o1',1,0),command('o2',1,10)]),[item])
    result=parse_items(entry([command('o1',1,0)]),[item])
    assert 'fin de session' in result.reprise['open']


def test_dirty_or_file_observation_does_not_supply_an_open_issue():
    session=entry([dict(ref='o1',kind='file',path='auth.py',at=0),
                   {**command('o2',0,10),'git_snapshot':{'dirty':True}}])
    for ref in ('o1','o2'):
        with pytest.raises(InvalidModelOutput):
            parse_items(session,[dict(text='Uncommitted work',kind='command_failure',evidence=[ref])])
    assert parse_items(session,[]).open_items==[]


def test_recorded_statement_requires_literal_quote_but_is_not_a_truth_oracle():
    session=entry([dict(ref='o1',kind='commit',at=0,message='Non corrigé :\ndivergence list/run.')])
    item=dict(text='Le message consigne une divergence.',kind='recorded_statement',evidence=['o1'],quote='Non corrigé : divergence list/run.')
    assert parse_items(session,[item]).open_items==[item]
    with pytest.raises(InvalidModelOutput,match='citation exacte'):
        parse_items(session,[{**item,'quote':'Invented text'}])
    # No regex pretends to establish that the model's interpretation follows.
    assert parse_items(session,[{**item,'text':'Unsupported interpretation'}]).open_items is not None


def previous(session):
    return dict(id='bbbbbbbbbbbbbbbb',session_ended_at=(session.started_at-timedelta(minutes=5)).isoformat(),
                event_id='old-source',workspace='/work/Pulse',label='old',
                reprise=dict(doing='Old inference',stopped_at='Old inference',open='Invented task'))


def test_previous_model_and_agent_are_context_not_open_evidence():
    session=entry([]); old=previous(session)
    agent=dict(workspace='/work/Pulse',started_at=session.started_at.isoformat(),
               ended_at=session.ended_at.isoformat(),summary='Implement X',event_id='agent-source')
    context=dict(last_session_summary=old,last_agent_session=agent)
    value=build_model_input(session,context,references=True)
    assert value['previous_summary']['origin']=='previous_model_interpretation'
    assert value['previous_summary']['evidence_eligible'] is False
    assert 'open_items' not in value['previous_summary']
    assert value['agent_session']['completion_state']=='unknown'
    assert input_provenance(session,context,value)['previous_summary:0']==['old-source']
    for ref in ('previous_summary:0','agent_request:0'):
        with pytest.raises(InvalidModelOutput):
            parse_items(session,[dict(text='X remains',kind='recorded_statement',evidence=[ref],quote='Invented task')],context)
    assert parse_items(session,[],context).open_items==[]


def test_future_or_known_foreign_summary_is_not_continuity():
    session=entry([]); old=previous(session)
    for replacement in (dict(workspace='/other'),dict(session_ended_at=session.ended_at.isoformat())):
        assert build_model_input(session,{'last_session_summary':{**old,**replacement}})['previous_summary'] is None


def test_new_generation_and_pending_recovery_keep_scope_and_provenance(fake_core,client,config,state):
    session=entry([command('o1',1,0)]); config=replace(config,prompt_version='v5')
    output=json.loads(valid_output());output['structured']['central_files']=[]
    output['reprise']['open']=[dict(text='pytest a terminé avec le code 1.',kind='command_failure',evidence=['o1'])]
    model=FakeSummarizer(json.dumps(output),model_id=config.model_id)
    result=summarize_session(session,client=client,summarizer=model,config=config,state=state,now=REFERENCE)
    assert result.status=='created'
    details=fake_core.posts[0]['details']
    assert details['open_items']==[dict(kind='command_failure',evidence=['o1'],scope='session_end')]
    assert details['observation_sources']['o1']==['event-o1']
    again=summarize_session(session,client=client,summarizer=model,config=config,state=state,now=REFERENCE)
    assert again.status=='already_known' and len(model.calls)==1


def test_v6_generates_without_annexes_under_its_own_identity(fake_core,client,config,state):
    from pulse_intelligence.provider_summarizer import prompt_path_for
    from pulse_intelligence.session_summary import summary_event_id
    session=entry([command('o1',1,0)]); old=previous(session)
    agent=dict(workspace='/work/Pulse',started_at=session.started_at.isoformat(),
               ended_at=session.ended_at.isoformat(),summary='Implement X',event_id='agent-source')
    from conftest import context_view
    ctx={**context_view(reference_at=session.ended_at),'last_session_summary':old,'last_agent_session':agent}
    assert build_model_input(session,ctx,references=True)['previous_summary'] is not None  # v5 l'aurait reçue
    fake_core.add_context(session.ended_at,ctx)
    output=json.loads(valid_output());output['structured']['central_files']=[];output['reprise']['open']=[]
    model=FakeSummarizer(json.dumps(output),model_id=config.model_id)
    v6=replace(config,prompt_version='v6')
    result=summarize_session(session,client=client,summarizer=model,config=v6,state=state,now=REFERENCE)
    assert result.status=='created'
    assert result.event_id==summary_event_id(session.id,'v6',config.model_id)!=summary_event_id(session.id,'v5',config.model_id)
    details=fake_core.posts[0]['details']
    assert details['prompt_version']=='v6'
    assert 'previous_summary:0' not in details['observation_sources'] and 'agent_request:0' not in details['observation_sources']
    # L'annexe est enregistrée absente, pas inconnue : `show` rend « aucune annexe ».
    assert 'previous_summary' in state.emitted[result.event_id] and state.emitted[result.event_id]['previous_summary'] is None
    prompt=prompt_path_for('v6').read_text(encoding='utf-8')
    assert 'annexe' not in prompt and 'previous_summary' not in prompt and 'agent_session' not in prompt
