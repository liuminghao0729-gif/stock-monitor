import time
from openbb import obb
tests = {
 'nasdaq.ownership.institutional': lambda: obb.nasdaq.equity.ownership.institutional(symbol='NVDA'),
 'nasdaq.ownership.short_interest': lambda: obb.nasdaq.equity.ownership.short_interest(symbol='NVDA'),
 'nasdaq.ownership.insider_trading': lambda: obb.nasdaq.equity.ownership.insider_trading(symbol='NVDA'),
 'nasdaq.estimates.consensus': lambda: obb.nasdaq.equity.estimates.consensus(symbol='NVDA'),
 'nasdaq.estimates.price_target': lambda: obb.nasdaq.equity.estimates.price_target(symbol='NVDA'),
 'nasdaq.calendar': lambda: obb.nasdaq.equity.calendar,
}
for k, f in tests.items():
    t=time.time()
    try:
        r=f()
        if hasattr(r,'results'):
            res=r.results; n=len(res) if hasattr(res,'__len__') else 1
            first=res[0] if isinstance(res,list) and res else res
            d=first.model_dump() if hasattr(first,'model_dump') else first
            print('OK ',k,n,'rows',round(time.time()-t,1),'s',{a:d[a] for a in list(d)[:7]} if isinstance(d,dict) else d)
        else: print('OBJ',k,[x for x in dir(r) if not x.startswith('_')])
    except Exception as e:
        print('ERR',k,type(e).__name__,str(e)[:140].replace('\n',' '))
