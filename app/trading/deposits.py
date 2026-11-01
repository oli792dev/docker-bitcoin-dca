"""Import booked fiat deposits without changing Bitcoin accounting or CSV exports."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.data.activity import append_activity_records


def sync_deposits(api, settings, state, now, cycle_start):
    identity=[settings['exchange'],settings['quote']]
    previous=state.get('deposit_history',{})
    start=0
    if previous.get('identity')==identity:
        # Revisit the active cycle and overlap recent history for delayed publication.
        since=datetime.fromisoformat(previous['checkedAt'])-timedelta(days=1)
        boundary=state.get('deposit_tracking',{}).get('dueAt')
        dates=[since,cycle_start]
        if boundary: dates.append(datetime.fromisoformat(boundary)-timedelta(days=1))
        start=max(0,int(min(d.astimezone(timezone.utc) for d in dates).timestamp()*1000))
    rows=api.fiat_deposits(settings['quote'],start,int(now.timestamp()*1000))
    if not isinstance(rows,list): raise ValueError('Fiat deposit history could not be verified')
    records=[]
    for item in rows:
        if item.get('status')!='completed' or item.get('symbol')!=settings['quote']: continue
        amount=Decimal(item['amount']);fee=Decimal(item.get('fee','0'))
        if not amount.is_finite() or not fee.is_finite() or amount<=0 or fee<0 or fee>amount:
            raise ValueError('Invalid fiat deposit amount or fee')
        timestamp=int(item['timestamp'])
        if not item.get('id') or timestamp<0: raise ValueError('Invalid fiat deposit reference or timestamp')
        if not start<=timestamp<=int(now.timestamp()*1000): continue
        records.append({'id':f"fiat-deposit:{settings['exchange']}:{settings['quote']}:{item['id']}",
            'exchange':settings['exchange'],'depositStatus':'confirmed',
            'row':{'datetime':datetime.fromtimestamp(timestamp/1000,timezone.utc).isoformat(),
                'type':'Deposit','identifier':settings['quote'],'assetType':'Cash',
                'currency':settings['quote'],'amount':str(amount),'fee':str(fee),
                'shares':'0','price':'0','tax':'0'}})
    # Insert before advancing the checkpoint; retrying the same exchange IDs is harmless.
    inserted=append_activity_records(records) if records else 0
    state['deposit_history']={'identity':identity,'checkedAt':now.isoformat()}
    return records,inserted
