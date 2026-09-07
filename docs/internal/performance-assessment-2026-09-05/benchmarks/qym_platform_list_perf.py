import os, json, time, statistics, gc
os.environ['QYM_DATABASE_URL']='sqlite:///:memory:'
from qym_platform_perf_audit import fixture
from qym_platform.db.models import Run,RunItem,RunItemScore,RunWorkflowStatus,User
from qym_platform.api.runs import legacy_list_runs
from qym_platform.auth import Principal

def bench(nruns,nitems):
    engine,factory,rid,counts=fixture()
    with factory() as db:
        base=db.get(Run,rid); base.status=RunWorkflowStatus.COMPLETED
        db.bulk_insert_mappings(Run,[dict(id=f'run-{r}',project_id='project',created_by_user_id='owner',owner_user_id='owner',task='benchmark',dataset='synthetic',metrics=['exact_match'],status=RunWorkflowStatus.COMPLETED,run_metadata={},run_config={}) for r in range(nruns-1)])
        ids=[rid]+[f'run-{r}' for r in range(nruns-1)]
        for run_id in ids:
            db.bulk_insert_mappings(RunItem,[dict(run_id=run_id,item_id=str(i),index=i,input='i'*1024,expected='e'*1024,output='o'*1024,latency_ms=float(i%100),item_metadata={'root_cause':'cause-'+str(i%5),'context':'m'*512}) for i in range(nitems)])
            db.bulk_insert_mappings(RunItemScore,[dict(run_id=run_id,item_id=str(i),metric_name='exact_match',score_numeric=float(i%2),score_raw=float(i%2),meta={}) for i in range(nitems)])
        db.commit()
    times=[]
    for repeat in range(3):
        with factory() as db:
            principal=Principal(user=db.get(User,'owner'),auth_type='none'); counts.clear(); start=time.perf_counter()
            result=legacy_list_runs(limit=100,offset=0,project_slug=None,status=None,exclude_live=False,include_total=True,user=None,user_id=None,owner_user_id=None,db=db,principal=principal)
            times.append(time.perf_counter()-start); sql=dict(counts)
        gc.collect()
    print(json.dumps({'test':'run_list','runs_returned':nruns,'source_items':nruns*nitems,'median_ms':round(statistics.median(times)*1000,1),'response_kib':round(len(json.dumps(result))/1024,1),'sql':sql}),flush=True)
    engine.dispose()
for n in [10,100]: bench(n,1000)
