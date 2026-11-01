"""Keep an unfunded monthly boundary open until usable fiat arrives."""
from datetime import datetime, timezone
import hashlib
import json
import uuid
from decimal import Decimal
from app.core.deposit_calendar import deposit_at


def observe_deposit(state, settings, now, cycle_start, next_deposit, balance):
    if not settings['live']:
        return next_deposit, False, False
    identity = [settings.get('exchange'), settings['quote'], settings['deposit_day'], settings.get('deposit_time','00:00'), settings['timezone']]
    previous = state.get('deposit_tracking', {})
    last_at = state.get('last_order_at')
    history = settings.get('startup_last_buy_at')
    last = datetime.fromisoformat(last_at) if last_at else history
    if last is not None:
        last = last.replace(tzinfo=last.tzinfo or timezone.utc).astimezone(timezone.utc)
    if previous.get('identity') == identity:
        due = datetime.fromisoformat(previous['dueAt'])
        expected = Decimal(previous['balance'])
        if last_at != previous.get('lastOrderAt'):
            expected -= Decimal(state.get('last_order_quote','0'))
        inflow = balance - expected
        waiting = bool(previous.get('waiting'))
        unverified = bool(previous.get('unverifiedBoundary'))
        first_due = bool(previous.get('firstPurchaseDue')) and last_at == previous.get('lastOrderAt')
    else:
        due = cycle_start if last is not None and last < cycle_start.astimezone(timezone.utc) else next_deposit
        inflow = Decimal(0)
        waiting = first_due = False
        unverified = now.astimezone(timezone.utc) >= due.astimezone(timezone.utc)
    if inflow >= Decimal('.01'):
        event_id = hashlib.sha256(json.dumps([previous, last_at, str(balance)], sort_keys=True).encode()).hexdigest()
        state['observed_deposit'] = {'id':'fiat-deposit:'+event_id, 'exchange':settings.get('exchange',''),
            'observed':True, 'row':{'datetime':now.isoformat(), 'type':'Deposit',
                'identifier':settings['quote'], 'assetType':'Cash', 'currency':settings['quote'],
                'amount':str(inflow), 'shares':'0', 'price':'0', 'fee':'0', 'tax':'0'}}
    expired = now.astimezone(timezone.utc) >= due.astimezone(timezone.utc)
    # An observed inflow on the due date also funds this cycle before its clock time.
    early_today = now.astimezone(due.tzinfo).date() == due.date()
    received = (expired or waiting or early_today) and inflow >= Decimal('.01')
    if received:
        if next_deposit.astimezone(timezone.utc) <= due.astimezone(timezone.utc):
            year, month = (due.year + 1, 1) if due.month == 12 else (due.year, due.month + 1)
            due = deposit_at(year, month, settings['deposit_day'], settings.get('deposit_time','00:00'), now.tzinfo)
        else:
            due = next_deposit
        expired = False
        first_due = True
        unverified = False
    state['deposit_tracking'] = {'identity':identity,'dueAt':due.isoformat(),
                                 'balance':str(balance),'lastOrderAt':last_at,'observationId':uuid.uuid4().hex,
                                 'waiting':waiting,'firstPurchaseDue':first_due,'unverifiedBoundary':unverified}
    return due, expired, received
