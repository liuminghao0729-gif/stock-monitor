import inspect, time
from openbb import obb
def sig(f):
    try: return str(inspect.signature(f))[:160]
    except Exception as e: return '?'
tests = {
 'sec.insider_trading': lambda: obb.sec.insider_trading(symbol='NVDA', limit=5),
 'sec.form_13f': lambda: obb.sec.form_13f(symbol='NVDA', limit=5),
 'sec.beneficial_ownership': lambda: obb.sec.beneficial_ownership(symbol='NVDA', limit=3),
 'finra.equity.shorts': lambda: obb.finra.equity.shorts.short_interest(symbol='NVDA'),
 'nasdaq.equity.historical': lambda: obb.nasdaq.equity.historical(symbol='NVDA', start_date='2016-01-01'),
 'nasdaq.equity.estimates': lambda: obb.nasdaq.equity.estimates,
 'nasdaq.equity.ownership': lambda: obb.nasdaq.equity.ownership,
 'cboe.equity.historical': lambda: obb.cboe.equity.historical(symbol='NVDA'),
}
for k, f in tests.items():
    t=time.time()
    try:
        r=f()
        if hasattr(r,'results') :
            res=r.results; n=len(res) if hasattr(res,'__len__') else 1
            first=res[0] if isinstance(res,list) and res else res
            d=first.model_dump() if hasattr(first,'model_dump') else first
            print('OK ',k,n,'rows',round(time.time()-t,1),'s',list(d)[:12] if isinstance(d,dict) else d)
        else:
            print('OBJ',k,[x for x in dir(r) if not x.startswith('_')])
    except Exception as e:
        print('ERR',k,type(e).__name__,str(e)[:150].replace('\n',' '))
