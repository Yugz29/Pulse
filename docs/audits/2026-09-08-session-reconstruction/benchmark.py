import json, sqlite3, statistics, tempfile, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from daemon_v2.trace_store import TraceStore, utc_lexical
from daemon_v2.ingest import normalize_event

def event(key):
    return normalize_event({'event_id':key,'schema_version':1,'type':'file_changed','producer':{'name':'pulse-benchmark'},'occurred_at':'2026-09-08T09:00:00+00:00','details':{'path':'/tmp/project/a.py','event':'modified'}})
results=[]
for count in (0,1000,10000,50000):
    with tempfile.TemporaryDirectory(prefix='pulse-session-bench-') as tmp:
        store=TraceStore(Path(tmp)/'trace.db')
        if count:
            store.append_event(event('seed'))
            with sqlite3.connect(store.database_path) as db:
                columns=[r[1] for r in db.execute('PRAGMA table_info(activities)') if r[1]!='id']
                template=dict(zip(columns,db.execute('SELECT '+','.join(columns)+' FROM activities').fetchone()))
                rows=[]
                for n in range(1,count):
                    row=template.copy(); row['event_id']=f'seed-{n}'
                    moment=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(minutes=n)
                    row['occurred_at']=moment.isoformat(); row['occurred_at_utc']=utc_lexical(moment)
                    if 'session_id' in row: row['session_id']=f'historical-{n//20}'
                    rows.append(tuple(row[c] for c in columns))
                db.executemany('INSERT INTO activities ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',rows)
        durations=[]
        for n in range(25):
            item=event(f'measured-{n}')
            start=time.perf_counter();store.append_event(item);durations.append(1000*(time.perf_counter()-start))
        results.append({'prior_rows':count,'n':25,'median_ms':round(statistics.median(durations),3),'min_ms':round(min(durations),3),'max_ms':round(max(durations),3)})
print(json.dumps(results,indent=2))
