"""Pure monthly withdrawal projection, independent of an executable buy schedule."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, DecimalException, ROUND_CEILING
from zoneinfo import ZoneInfo
from app.core.deposit_calendar import deposit_at
from app.core.planning import plan_order

DESCRIPTION = 'Estimate at the current BTC price, deposit and purchase interval'


def withdrawal_forecast(settings, snapshot, monthly_deposit, now):
    if not settings.get('withdrawals_enabled'): return None, 'Automatic withdrawals disabled'
    if not settings.get('live'): return None, 'Unavailable in simulation mode'
    try:
        monthly = Decimal(str(monthly_deposit))
        balance, price = Decimal(str(snapshot['btcBalance'])), Decimal(str(snapshot['price']))
        threshold = Decimal(str(settings['withdraw_threshold']))
        if any(not v.is_finite() or v < 0 for v in (monthly,balance,price,threshold)) or price <= 0 or threshold <= 0:
            raise ValueError('Invalid forecast input')
        if balance * price >= threshold: return now.isoformat(), 'Threshold reached; awaiting automatic withdrawal check'
        plan = snapshot['withdrawalForecastPlan']
        quantity, cost = Decimal(plan['orderAmount']), Decimal(plan['plannedCost'])
        base_quantity = Decimal(plan.get('baseOrderAmount',plan['orderAmount']))
        base_cost = Decimal(plan.get('basePlannedCost',plan['plannedCost']))
        budget = Decimal(plan['budget'])
        if any(not v.is_finite() or v <= 0 for v in (quantity,cost,base_quantity,base_cost)) or not budget.is_finite() or budget < 0:
            raise ValueError('Invalid forecast reference')
        zone = ZoneInfo(settings.get('timezone','UTC'))
        now = now.astimezone(timezone.utc)
        expected = datetime.fromisoformat(plan['nextDepositAt']).astimezone(zone)
        overdue = expected.astimezone(timezone.utc) < now
        funding = max(expected.astimezone(timezone.utc),now)
        raw_due = snapshot.get('nextPurchaseAt')
        due = max(now,datetime.fromisoformat(raw_due.replace('Z','+00:00'))) if raw_due else now
        interval = max(60,int(plan.get('intervalSeconds',300)))
        remaining = threshold / price - balance
        description = DESCRIPTION + (' · assumes overdue deposit arrives now' if overdue else '')
        for _ in range(1200):
            slots = max(0,int((funding-due).total_seconds()//interval)+1)
            count = min(int(budget//cost),slots)
            if count:
                tail_quantity,tail_cost = quantity,cost
                if count == int(budget//cost) and plan.get('marketRules'):
                    tail=plan_order(plan['marketRules'],base_quantity,price,plan['feeRate'],budget-cost*(count-1))
                    tail_quantity,tail_cost=tail.quantity,tail.cost
                regular = min(count-1,int((remaining/quantity).to_integral_value(rounding=ROUND_CEILING)))
                if remaining <= quantity*regular:
                    return (due+timedelta(seconds=(regular-1)*interval)).isoformat(),description
                if remaining <= quantity*(count-1)+tail_quantity:
                    return (due+timedelta(seconds=(count-1)*interval)).isoformat(),description
                remaining -= quantity*(count-1)+tail_quantity
                budget -= cost*(count-1)+tail_cost
            if monthly == 0: return None, 'Enter an expected monthly deposit to project further purchases'
            budget += monthly
            start = funding.astimezone(zone)
            year,month=(start.year+1,1) if start.month==12 else (start.year,start.month+1)
            funding=deposit_at(year,month,settings['deposit_day'],settings.get('deposit_time','00:00'),zone).astimezone(timezone.utc)
            quantity,cost=base_quantity,base_cost
            count=int(budget//cost)
            # A deposit releases the first purchase immediately; remaining buys
            # share the rest of the calendar period and finish before its boundary.
            due=start.astimezone(timezone.utc)
            interval=max(60,int((funding-due).total_seconds()/max(1,count)))
        return None,'Estimate exceeds the 100-year forecast horizon'
    except (KeyError,TypeError,ValueError,DecimalException,OverflowError):
        return None,'Waiting for account price and order minimums'
