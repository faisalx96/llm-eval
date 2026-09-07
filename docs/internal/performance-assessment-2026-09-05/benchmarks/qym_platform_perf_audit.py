import asyncio, collections, gc, json, os, statistics, time, tracemalloc, uuid
os.environ['QYM_DATABASE_URL']='sqlite:///:memory:'
os.environ['QYM_AUTH_MODE']='none'
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from qym_platform.db.base import Base
from qym_platform.db.models import User, UserRole, Project, Run, RunItem, RunItemScore, RunWorkflowStatus, Span, RunTraceAggregate
from qym_platform.api.runs import _build_run_data
from qym_platform.api.ingest import ingest_events, _refresh_live_trace_stats, _empty_trace_bucket
from qym_platform.auth import Principal

def fixture(n=0):
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine, autoflush=False)
    db=factory()
    owner=User(id='owner',email='bench@example.invalid',role=UserRole.ADMIN)
    project=Project(id='project',name='Benchmark',slug='bench',created_by_user_id=owner.id)
    run=Run(id=str(uuid.uuid4()),project_id=project.id,created_by_user_id=owner.id,owner_user_id=owner.id,task='benchmark',dataset='synthetic',metrics=['exact_match'],status=RunWorkflowStatus.RUNNING,run_metadata={},run_config={})
    db.add_all([owner,project,run]); db.commit(); rid=run.id
    if n:
        db.bulk_insert_mappings(RunItem,[dict(run_id=rid,item_id=str(i),index=i,input={'text':'i'*1024},expected={'text':'e'*1024},output={'text':'o'*1024},latency_ms=float(i%100),item_metadata={'task_started_at_ms':1,'context':'m'*512},trace_id=f'trace-{i}') for i in range(n)])
        db.bulk_insert_mappings(RunItemScore,[dict(run_id=rid,item_id=str(i),metric_name='exact_match',score_numeric=float(i%2),score_raw=float(i%2),meta={}) for i in range(n)])
        db.commit()
    db.close()
    counts=collections.Counter()
    event.listen(engine,'before_cursor_execute',lambda conn,cursor,statement,parameters,context,executemany: counts.update([statement.lstrip().split()[0].upper()]))
    return engine,factory,rid,counts

def detail(n):
    engine,factory,rid,counts=fixture(n)
    times=[]
    for repeat in range(3):
        with factory() as db:
            run=db.get(Run,rid); counts.clear()
            t=time.perf_counter(); result=_build_run_data(db,run); built=time.perf_counter()-t
            t=time.perf_counter(); encoded=json.dumps(result); ser=time.perf_counter()-t
            times.append((built,ser)); sql=dict(counts)
        del result,encoded; gc.collect()
    with factory() as db:
        run=db.get(Run,rid); tracemalloc.start(); result=_build_run_data(db,run); encoded=json.dumps(result); _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop(); size=len(encoded.encode()); rows=len(result['snapshot']['rows'])
    out=dict(test='run_detail',items=n,rows=rows,build_ms=round(statistics.median(x[0] for x in times)*1000,1),json_ms=round(statistics.median(x[1] for x in times)*1000,1),response_mib=round(size/2**20,2),peak_python_mib=round(peak/2**20,2),sql=sql)
    engine.dispose(); print(json.dumps(out),flush=True)

def trace_refresh(n):
    engine,factory,rid,counts=fixture(n)
    with factory() as db:
        bucket=_empty_trace_bucket(); bucket['span_count']=1; bucket['tokens']=1
        db.bulk_insert_mappings(RunTraceAggregate,[dict(run_id=rid,trace_id=f'trace-{i}',span_count=1,tokens=1,raw_bucket=bucket) for i in range(n)])
        db.add(Span(run_id=rid,trace_id='trace-0',span_id='span-0',name='llm',kind='CLIENT',status='OK',duration_ms=1,attributes={'openinference.span.kind':'LLM','llm.token_count.total':1},events=[],links=[]))
        db.commit(); run=db.get(Run,rid); _refresh_live_trace_stats(db,run,touched_trace_ids={'trace-0'}); db.commit()
    times=[]
    for repeat in range(3):
        with factory() as db:
            run=db.get(Run,rid); counts.clear(); t=time.perf_counter(); _refresh_live_trace_stats(db,run,touched_trace_ids={'trace-0'}); db.commit(); elapsed=time.perf_counter()-t
            times.append(elapsed); sql=dict(counts)
        gc.collect()
    print(json.dumps(dict(test='trace_refresh_single_touched_trace',items=n,median_ms=round(statistics.median(times)*1000,1),sql=sql)),flush=True)
    engine.dispose()

class Request:
    def __init__(self,body): self.data=body
    async def body(self):
        await asyncio.sleep(0)
        return self.data

async def ingest(n,kind):
    engine,factory,rid,counts=fixture()
    async def tick(gaps):
        prev=time.perf_counter()
        while True:
            await asyncio.sleep(.001)
            now=time.perf_counter(); gaps.append(now-prev); prev=now
    events=[]
    for i in range(n):
        payload={'item_id':str(i),'index':i,'input':'input'} if kind=='item_started' else {'trace_id':'trace-0','span_id':f'span-{i}','name':'span','duration_ms':1,'attributes':{}}
        events.append(dict(version=1,event_id=str(uuid.uuid4()),sequence=i+1,type=kind,sent_at='2026-09-05T00:00:00Z',run_id=rid,payload=payload))
    request=Request(('\n'.join(json.dumps(x) for x in events)).encode())
    with factory() as db:
        principal=Principal(user=db.get(User,'owner'),auth_type='api_key',scopes=('runs:write',),project_id='project')
        gaps=[]; ticker=asyncio.create_task(tick(gaps)); await asyncio.sleep(.005); counts.clear()
        t=time.perf_counter(); result=await ingest_events(rid,request,db,principal); elapsed=time.perf_counter()-t
        await asyncio.sleep(.005); ticker.cancel()
        print(json.dumps(dict(test='ingest',event=kind,events=n,elapsed_ms=round(elapsed*1000,1),max_event_loop_gap_ms=round(max(gaps)*1000,1),sql=dict(counts),response=json.loads(result.body))),flush=True)
    engine.dispose()

if __name__=='__main__':
    for n in [1000,10000]: detail(n)
    for n in [100,1000,10000]: trace_refresh(n)
    for kind in ['item_started','span_completed']:
        for n in [100,500,1000]: asyncio.run(ingest(n,kind))
