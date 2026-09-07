import json,secrets,statistics,time
from qym_platform.security import hash_api_key,verify_api_key
key=secrets.token_urlsafe(32)
hashed=hash_api_key(key)
timings=[]
for _ in range(10):
    start=time.perf_counter(); assert verify_api_key(key,hashed); timings.append(time.perf_counter()-start)
print(json.dumps({'test':'API_key_PBKDF2_600k','median_ms':round(statistics.median(timings)*1000,1),'min_ms':round(min(timings)*1000,1),'max_ms':round(max(timings)*1000,1),'iterations':10}))
