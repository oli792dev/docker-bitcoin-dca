"""Review regressions with synthetic data; all exchange IO is mocked."""
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch
from app.data import activity
from app.data import analytics
from app.trading import bot
from app.data import reporting
from app.webpage import web_ui
from app.trading import withdrawals
from app.exchanges import market_prices
from app.trading import worker
from app.core import healthcheck
from app.exchanges.exchange_errors import DefinitiveRejection


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name,value in [('ACTIVITY_PATH',self.root/'activity.json'),('SNAPSHOT_PATH',self.root/'dashboard.json')]:
            p=patch.object(activity,name,value);p.start();self.addCleanup(p.stop)
        self.settings={'exchange':'KRAKEN','quote':'EUR','live':True,'timezone':'Europe/Berlin','deposit_day':1,
                       'buy_amount':D(0),'withdrawals_enabled':False,'withdraw_threshold':D(1000),
                       'startup_delay_seconds':0,'order_status_check_seconds':30}

    def record(self, id='buy', kind='Buy', currency='EUR', status=None, when='2026-10-20T12:00:00Z'):
        r={'id':id,'exchange':'KRAKEN','row':{'datetime':when,'type':kind,'identifier':'BTC','assetType':'Crypto',
                                          'shares':'.0045','amount':'359','fee':'.8975','price':'80000','currency':currency,'tax':'0'}}
        if kind=='TransferOut':
            r.update(netWithdrawalAmount=True,networkFeeBtc='.0001',grossWithdrawalAmountBtc='.0045')
            r['row'].update(shares='.0044',amount='352',fee='8')
            if status:r['withdrawalStatus']=status
        return r

    def test_initialized_database_reads_skip_schema_work_and_unknown_versions_fail_closed(self):
        import sqlite3
        activity.append_activity_records([self.record()])
        statements=[];connect=sqlite3.connect
        def traced(*args,**kwargs):
            db=connect(*args,**kwargs);db.set_trace_callback(statements.append);return db
        with patch.object(activity.sqlite3,'connect',side_effect=traced):
            self.assertEqual(len(activity.read_activity_records()),1)
        self.assertFalse(any('CREATE ' in statement.upper() for statement in statements))
        with connect(activity.ACTIVITY_PATH.with_suffix('.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            db.execute('PRAGMA user_version=2')
        with self.assertRaisesRegex(ValueError,'newer'):activity.read_activity_records()
        with connect(activity.ACTIVITY_PATH.with_suffix('.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM activity').fetchone()[0],1)

    def test_failed_ledger_initialization_retries_without_partial_import(self):
        records=[self.record('first'),self.record('invalid')]
        records[1]['row']['datetime']='invalid timestamp'
        activity.ACTIVITY_PATH.write_text(json.dumps(records))
        with self.assertRaises(ValueError):activity.read_activity_records()
        import sqlite3
        with sqlite3.connect(activity.ACTIVITY_PATH.with_suffix('.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM activity').fetchone()[0],0)
        activity.ACTIVITY_PATH.write_text(json.dumps([self.record('first')]))
        self.assertEqual(len(activity.read_activity_records()),1)

    def test_json_migration_is_once_and_preserves_source_and_metadata(self):
        r=self.record('old','TransferOut');r['manual']=True
        text=json.dumps({'records':[r]});activity.ACTIVITY_PATH.write_text(text)
        got=activity.read_activity_records()[0]
        self.assertEqual(got['id'],'old');self.assertEqual(got['row'],r['row']);self.assertTrue(got['manual'])
        self.assertEqual(got['networkFeeBtc'],'.0001');self.assertEqual(got['withdrawalStatus'],'legacy_unverified')
        self.assertEqual(activity.ACTIVITY_PATH.read_text(),text)
        self.assertEqual(activity.append_activity_records([r]),0)
        activity.ACTIVITY_PATH.write_text('not valid JSON any longer')
        self.assertEqual(len(activity.read_activity_records()),1)

    def test_net_wallet_amount_and_gross_balance_have_distinct_meanings(self):
        buys=self.record();out=self.record('withdraw','TransferOut',status='completed')
        activity.append_activity_records([buys,out])
        self.assertEqual(activity.ledger_balance(),D(0))
        row=reporting.parqet_aggregate_rows([buys,out],'KRAKEN')[0]
        self.assertEqual(D(row['shares']),D('.0044'))
        out['withdrawalStatus']='failed';activity.update_activity_record(out)
        self.assertEqual(activity.ledger_balance(),D('.0045'))

    def test_only_confirmed_withdrawals_can_be_exported(self):
        for status in (None,'legacy_unverified','submitted','failed','canceled'):
            self.assertEqual(reporting.parqet_aggregate_rows([self.record(),self.record('w','TransferOut',status=status)],'KRAKEN'),[])

    def test_status_lookup_does_not_treat_settled_as_completed(self):
        record=self.record('withdrawal:ref','TransferOut',status='submitted');record['withdrawalId']='ref'
        activity.append_activity_records([record])
        api=Mock();api.btc_withdrawals.return_value=[{'id':'ref','status':'settled','amount':'.0044','fee':'.0001'}]
        withdrawals.reconcile_withdrawals(api,self.settings,force=True)
        self.assertEqual(activity.get_activity_record(record['id'])['withdrawalStatus'],'submitted')
        api.btc_withdrawals.return_value=[{'id':'ref','status':'completed','amount':'.0044','fee':'.0001'}]
        withdrawals.reconcile_withdrawals(api,self.settings,force=True)
        self.assertEqual(activity.get_activity_record(record['id'])['withdrawalStatus'],'completed')

    def test_ambiguous_history_does_not_confirm_or_duplicate_withdrawals(self):
        record=self.record('withdrawal:ref','TransferOut',status='submitted');record['withdrawalId']='ref'
        activity.append_activity_records([record])
        api=Mock();api.btc_withdrawals.return_value=[{'id':'ref','status':'completed'}]*2
        withdrawals.reconcile_withdrawals(api,self.settings,force=True)
        self.assertEqual(activity.get_activity_record(record['id'])['withdrawalStatus'],'submitted')
        api.withdraw_btc.assert_not_called()

    def test_pagination_transfers_only_requested_rows_and_keeps_exact_totals(self):
        records=[self.record(str(i)) for i in range(105)]
        activity.append_activity_records(records)
        page,total,n,groups,_=activity.read_report(0,2**62,3,20)
        self.assertEqual((len(page),total,n),(20,105,3))
        self.assertEqual(D(groups[0]['amount']),D(359)*105)
        self.assertEqual(D(groups[0]['fee']),D('.8975')*105)
        summary=analytics.report(self.settings,groups,{},page)
        self.assertEqual(summary['summary']['buyCount'],105)
        self.assertEqual(len(summary['activities']),20)
        page,total,n,_,_=activity.read_report(0,2**62,100,20)
        self.assertEqual((len(page),n),(5,6))

    def test_mixed_currency_totals_are_separate(self):
        a=self.record('eur');b=self.record('usd',currency='USD')
        activity.append_activity_records([a,b])
        result=analytics.report(self.settings,activity.activity_totals(),{},[a,b])
        self.assertIsNone(result['summary']['buyVolume'])
        self.assertEqual(result['summaryByCurrency']['EUR']['buyVolume'],'359')
        self.assertEqual(result['summaryByCurrency']['USD']['buyVolume'],'359')

    def test_browser_price_reads_never_fetch_external_prices(self):
        snapshot={'exchange':'KRAKEN','quote':'EUR','marketPrices':{'EUR':'80000','USD':'88000'},
                  'updatedAt':datetime.now(timezone.utc).isoformat()}
        handler=object.__new__(web_ui.Handler);handler.path='/api/market-price?currency=USD'
        handler.settings=self.settings;handler._require_authentication=lambda:True;handler._json=Mock()
        with patch.object(web_ui,'read_dashboard_snapshot',return_value=snapshot),patch.object(market_prices.requests,'get',side_effect=AssertionError('browser network request')):
            handler.do_GET();first=handler._json.call_args.args[1]
            handler.do_GET();self.assertEqual(first,handler._json.call_args.args[1])
        self.assertEqual(first['price'],'88000');self.assertEqual(first['conversionRate'],'1.1')
        self.assertEqual(first['updatedAt'],datetime.fromisoformat(snapshot['updatedAt']).timestamp())
        with self.assertRaises(RuntimeError):market_prices.snapshot_market_price(snapshot,'BITVAVO','EUR','EUR')
        snapshot['marketPrices']={'EUR':'80000'}
        self.assertEqual(market_prices.snapshot_market_price(snapshot,'KRAKEN','EUR','EUR')['price'],'80000')

    def test_historical_rates_are_cached_once_per_trade_day(self):
        record=self.record(currency='USD',when='2026-10-25T12:00:00Z')
        response=Mock();response.json.return_value={'rates':{'2026-10-23':{'EUR':'.9'}}}
        with patch.object(reporting.requests,'get',return_value=response) as fetch:
            first=reporting._usd_eur_rates([record['row']]*100)
            second=reporting._usd_eur_rates([record['row']]*100)
        self.assertEqual(fetch.call_count,1);self.assertEqual(first,second)
        self.assertEqual(reporting._purchase_cost_eur(record['row'],first),D('359.8975')*D('.9'))

    def cycle_api(self):
        api=Mock();api.fiat_deposits.return_value=[];api.balance.return_value=D(100);api.price.return_value=D(80000)
        api.market.return_value={'status':'trading','minOrderInQuoteAsset':'5','minOrderInBaseAsset':'.0001','quantityDecimals':8,'notionalDecimals':2}
        api.estimate_taker_fee.return_value=D('.0025')
        return api

    def test_definitive_rejection_clears_pending_but_timeout_keeps_it(self):
        for exception, retained in [(DefinitiveRejection('Rejected: insufficient funds'),False),(__import__('requests').ReadTimeout('unknown'),True)]:
            state={};api=self.cycle_api();api.buy_btc.side_effect=exception
            with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'):
                bot.run_once(api,dict(self.settings),300)
            self.assertEqual(bool(state.get('pending_order')),retained)
            self.assertEqual(api.buy_btc.call_count,1)

    def test_dry_run_debits_fees_and_reads_market_once(self):
        state={};api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'):
            bot.run_once(api,{**self.settings,'live':False},300)
        self.assertEqual(D(state['spent']),D('8.02'))
        self.assertEqual(api.balance.call_count,2);self.assertEqual(api.market.call_count,1);self.assertEqual(api.price.call_count,2)

    def test_periodic_checks_do_not_move_due_time_when_inputs_are_unchanged(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        state={'last_order_at':(now-timedelta(hours=1)).isoformat()}
        settings={**self.settings,'first_purchase_done':True}
        api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'):
            with patch.object(bot,'local_now',return_value=now):bot.run_once(api,settings,300)
            first=state['schedule']['dueAt']
            with patch.object(bot,'local_now',return_value=now+timedelta(minutes=5)):bot.run_once(api,settings,300)
        self.assertEqual(state['schedule']['dueAt'],first)
        api.buy_btc.assert_not_called()

    def test_confirmed_purchase_replans_even_if_balance_has_not_updated(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        state={};api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'):
            with patch.object(bot,'local_now',return_value=now):
                bot.run_once(api,self.settings,300,schedule_only=True)
                state['last_order_at']=now.isoformat()
                bot.run_once(api,self.settings,300)
        self.assertGreater(datetime.fromisoformat(state['schedule']['dueAt']),now)
        api.buy_btc.assert_not_called()

    def test_restart_logs_purchase_anchor_elapsed_due_and_wait_once(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        last=now-timedelta(hours=1)
        settings={**self.settings,'startup_last_buy_at':last,'startup_schedule_log_pending':True}
        state={};api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'),patch.object(bot,'local_now',return_value=now):
            with self.assertLogs(bot.LOG,level='INFO') as logs:
                bot.run_once(api,settings,300)
                bot.run_once(api,settings,300)
        lines=[line for line in logs.output if 'Restart alignment:' in line]
        self.assertEqual(len(lines),1)
        self.assertIn('last purchase=2026-10-28T12:00:00+01:00',lines[0])
        self.assertIn('elapsed since purchase=60.0 minutes',lines[0])
        self.assertIn('calculated purchase interval=',lines[0])
        self.assertIn('next purchase=',lines[0]);self.assertIn('remaining wait=',lines[0])
        api.buy_btc.assert_not_called()

    def test_each_periodic_check_logs_actual_due_time_and_remaining_minutes(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        state={'last_order_at':(now-timedelta(hours=1)).isoformat()}
        settings={**self.settings,'first_purchase_done':True}
        api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'):
            with self.assertLogs(bot.LOG,level='INFO') as logs:
                with patch.object(bot,'local_now',return_value=now):bot.run_once(api,settings,300)
                first=state['schedule']['dueAt']
                with patch.object(bot,'local_now',return_value=now+timedelta(minutes=5)):bot.run_once(api,settings,300)
        lines=[line for line in logs.output if 'Purchase schedule:' in line]
        self.assertEqual(len(lines),2)
        self.assertIn('elapsed since purchase=60.0 minutes',lines[0])
        self.assertIn('elapsed since purchase=65.0 minutes',lines[1])
        self.assertIn('remaining wait=',lines[1])
        self.assertIn('saved due time retained for unchanged inputs',lines[1])
        due=datetime.fromisoformat(first).astimezone(bot.ZoneInfo('Europe/Berlin')).isoformat(timespec='seconds')
        self.assertTrue(all('next purchase='+due in line for line in lines))
        api.buy_btc.assert_not_called()

    def test_last_affordable_purchase_is_not_lost_to_the_old_buffer_or_boundary(self):
        now=datetime(2026,10,31,18,tzinfo=timezone.utc)
        state={'last_order_at':datetime(2026,10,31,tzinfo=timezone.utc).isoformat()}
        api=self.cycle_api();api.balance.return_value=D('8.02')
        with patch.object(bot,'local_now',return_value=now.astimezone(bot.ZoneInfo('Europe/Berlin'))),patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule') as schedule:
            bot.run_once(api,self.settings,300,schedule_only=True)
            plan=schedule.call_args.args[2]
            self.assertEqual(D(plan['plannedCost']),D('8.02'))
            self.assertLess(datetime.fromisoformat(state['schedule']['dueAt']),datetime.fromisoformat(plan['nextDepositAt']))
            bot.run_once(api,self.settings,300)
        api.buy_btc.assert_called_once()

    def test_confirmed_fiat_deposits_are_visible_once_but_do_not_change_exports_or_totals(self):
        now=datetime(2026,10,21,10,tzinfo=bot.ZoneInfo('Europe/Berlin'))
        api=self.cycle_api();api.balance.return_value=D('10')
        state={}
        with patch.object(bot,'local_now',return_value=now),patch.object(bot,'read_state',side_effect=lambda *args:state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'):
            bot.run_once(api,self.settings,300,schedule_only=True)
            baseline=json.loads(json.dumps(state))
            api.balance.return_value=D('210')
            api.fiat_deposits.return_value=[{'id':'bank-1','status':'completed','symbol':'EUR','amount':'200','fee':'0','timestamp':int(now.timestamp()*1000)}]
            bot.run_once(api,self.settings,300,schedule_only=True)
            # Replay after an interrupted state write must not duplicate the ledger entry.
            state=json.loads(json.dumps(baseline))
            bot.run_once(api,self.settings,300,schedule_only=True)
        deposits=activity.read_activity_records()
        self.assertEqual(len(deposits),1)
        self.assertEqual(deposits[0]['row']['amount'],'200')
        self.assertEqual(deposits[0]['row']['identifier'],'EUR')
        buy=self.record();out=self.record('out','TransferOut',status='completed',when='2026-10-22T12:00:00Z')
        expected=reporting.parqet_aggregate_rows([buy,out],'KRAKEN')
        self.assertEqual(reporting.parqet_aggregate_rows([buy,*deposits,out],'KRAKEN'),expected)
        activity.append_activity_records([buy,out])
        records,total,page,groups,balance=activity.read_report(0,2**63-1)
        self.assertEqual(total,3)
        self.assertTrue(any(r['row']['type']=='Deposit' for r in records))
        self.assertTrue(all(g['kind']!='Deposit' for g in groups))
        self.assertEqual(reporting.parqet_aggregate_rows(activity.parqet_interval_records(0,2**63-1),'KRAKEN'),expected)

    def test_early_deposit_advances_deadline_once_and_survives_restart(self):
        from app.trading.funding import observe_deposit
        zone=bot.ZoneInfo('Europe/Berlin')
        settings={**self.settings,'deposit_day':1,'deposit_time':'12:00'}
        state={}
        now=datetime(2026,11,1,8,tzinfo=zone)
        deposits=[]
        def observe(balance):
            _,start,next_at=bot.cycle_dates(now,1,'12:00')
            return observe_deposit(state,settings,now,start,next_at,D(balance),deposits)
        observe('0.45')
        deposits.append({'row':{'datetime':now.isoformat(),'amount':'200'}})
        due,expired,received=observe('200.45')
        self.assertEqual(due,datetime(2026,12,1,12,tzinfo=zone))
        self.assertFalse(expired);self.assertTrue(received)
        state=json.loads(json.dumps(state))
        state['last_order_at']=now.isoformat();state['last_order_quote']='4'
        due,expired,received=observe('196.45')
        self.assertFalse(received);self.assertFalse(expired)
        now=datetime(2026,11,1,13,tzinfo=zone)
        self.assertEqual(observe('196.45')[0],due)
        self.assertFalse(observe('196.45')[2])
        # The next due date, including year rollover, still uses its configured clock.
        now=datetime(2026,12,1,8,tzinfo=zone)
        deposits.append({'row':{'datetime':now.isoformat(),'amount':'200'}})
        self.assertEqual(observe('396.45')[0],datetime(2027,1,1,12,tzinfo=zone))

    def test_late_deposit_wait_survives_restart_and_own_purchase_is_not_a_deposit(self):
        now=datetime(2026,11,1,1,tzinfo=timezone.utc)
        state={'last_order_at':'2026-10-30T12:00:00+00:00'}
        api=self.cycle_api();api.balance.return_value=D('8.02')
        with patch.object(bot,'local_now',return_value=now.astimezone(bot.ZoneInfo('Europe/Berlin'))),patch.object(bot,'read_state',side_effect=lambda *args:state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule') as schedule:
            bot.run_once(api,self.settings,300,schedule_only=True)
            self.assertLessEqual(datetime.fromisoformat(state['schedule']['dueAt']),now)
            self.assertEqual(datetime.fromisoformat(state['deposit_tracking']['dueAt']).month,11)
            state['last_order_at']=now.isoformat();state['last_order_quote']='8.02'
            state=json.loads(json.dumps(state))
            api.balance.return_value=D('0')
            bot.run_once(api,self.settings,300)
            self.assertEqual(schedule.call_args.args[:2],(None,'Waiting for deposit'))
            self.assertEqual(D(schedule.call_args.args[2]['budget']),D(0))
            self.assertEqual(datetime.fromisoformat(state['deposit_tracking']['dueAt']).month,11)
            state=json.loads(json.dumps(state))
            api.balance.return_value=D('200')
            api.fiat_deposits.return_value=[{'id':'late','status':'completed','symbol':'EUR','amount':'200','fee':'0','timestamp':int(now.timestamp()*1000)}]
            bot.run_once(api,self.settings,300,schedule_only=True)
            self.assertEqual(datetime.fromisoformat(state['deposit_tracking']['dueAt']).month,12)
            self.assertEqual(datetime.fromisoformat(state['schedule']['dueAt']),now.astimezone(bot.ZoneInfo('Europe/Berlin')))
            api.buy_btc.assert_not_called()

    def test_upgrade_with_unknown_large_balance_does_not_drain_it_as_old_residual(self):
        now=datetime(2026,11,1,1,tzinfo=timezone.utc)
        state={'last_order_at':'2026-10-30T12:00:00+00:00'}
        api=self.cycle_api();api.balance.return_value=D('200')
        with patch.object(bot,'local_now',side_effect=lambda *args:now.astimezone(bot.ZoneInfo('Europe/Berlin'))),patch.object(bot,'read_state',side_effect=lambda *args:state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule') as schedule:
            bot.run_once(api,self.settings,300,schedule_only=True)
            self.assertEqual(datetime.fromisoformat(state['deposit_tracking']['dueAt']).month,12)
            state['last_order_at']=now.isoformat();state['last_order_quote']='8.02'
            api.balance.return_value=D('191.98');now+=timedelta(minutes=1)
            bot.run_once(api,self.settings,300,schedule_only=True)
            self.assertGreater(datetime.fromisoformat(state['schedule']['dueAt']),now)
            self.assertFalse(state['deposit_tracking']['firstPurchaseDue'])
            api.buy_btc.assert_not_called()

    def test_deposit_clock_controls_boundary_and_purchase_interval(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        api=self.cycle_api();state={'last_order_at':(now-timedelta(minutes=1)).isoformat()}
        settings={**self.settings,'deposit_time':'09:30'}
        with patch.object(bot,'local_now',return_value=now.astimezone(bot.ZoneInfo('Europe/Berlin'))),patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule') as schedule:
            bot.run_once(api,settings,300,schedule_only=True)
        plan=schedule.call_args.args[2]
        self.assertEqual(datetime.fromisoformat(plan['nextDepositAt']).hour,9)
        self.assertEqual(datetime.fromisoformat(plan['nextDepositAt']).minute,30)
        self.assertEqual(datetime.fromisoformat(plan['nextDepositAt']).utcoffset(),timedelta(hours=1))
        possible=int(D(plan['budget'])//D(plan['plannedCost']))
        expected=int((datetime.fromisoformat(plan['nextDepositAt']).astimezone(timezone.utc)-datetime.fromisoformat(state['last_order_at'])).total_seconds()/(possible+1))
        self.assertEqual(plan['intervalSeconds'],expected)
        before=datetime(2026,10,31,9,29,tzinfo=timezone.utc)
        self.assertEqual(bot.cycle_dates(before,31,'09:30')[2].month,10)
        self.assertEqual(bot.cycle_dates(before+timedelta(minutes=1),31,'09:30')[2].day,30)

    def test_local_deposit_clock_handles_short_months_and_dst_gaps_and_folds(self):
        from app.core.deposit_calendar import deposit_at
        zone=bot.ZoneInfo('Europe/Berlin')
        self.assertEqual(deposit_at(2028,2,31,'09:30',zone).day,29)
        self.assertEqual(deposit_at(2027,2,31,'09:30',zone).day,28)
        self.assertEqual(deposit_at(2026,3,29,'02:30',zone).isoformat(),'2026-03-29T03:30:00+02:00')
        repeated=deposit_at(2026,10,25,'02:30',zone)
        self.assertEqual(repeated.utcoffset(),timedelta(hours=2))
        second=datetime(2026,10,25,2,15,tzinfo=zone,fold=1)
        self.assertEqual(bot.cycle_dates(second,25,'02:30')[2].month,11)
        self.assertEqual(bot.cycle_dates(datetime(2026,12,31,23,59,tzinfo=zone),31,'23:59')[2].year,2027)

    def test_interval_uses_last_purchase_to_deposit_including_dst_boundary(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        for last in (now-timedelta(hours=2),now-timedelta(days=4)):
            with self.subTest(last=last):
                state={'last_order_at':last.isoformat()};api=self.cycle_api()
                with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'),patch.object(bot,'local_now',return_value=now.astimezone(bot.ZoneInfo('Europe/Berlin'))):
                    bot.run_once(api,self.settings,300,schedule_only=True)
                deposit=bot.cycle_dates(now.astimezone(bot.ZoneInfo('Europe/Berlin')),1)[2]
                # Available budget 100 / (8 + .02 fee = 8.02; 12 buys and one trailing time slot) = 12 buys.
                seconds=int((deposit.astimezone(timezone.utc)-last).total_seconds()/13)
                self.assertEqual(datetime.fromisoformat(state['schedule']['dueAt']),last+timedelta(seconds=seconds))
                api.buy_btc.assert_not_called()

    def test_interval_without_previous_purchase_starts_now(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc);state={};api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'),patch.object(bot,'local_now',return_value=now.astimezone(bot.ZoneInfo('Europe/Berlin'))):
            with self.assertLogs(bot.LOG,level='INFO') as logs:
                bot.run_once(api,self.settings,300,schedule_only=True)
        self.assertEqual(datetime.fromisoformat(state['schedule']['dueAt']),now)
        self.assertTrue(any('no previous purchase time available' in line for line in logs.output))

    def test_old_saved_due_time_is_recalculated_with_new_interval_rule(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc);last=now-timedelta(hours=2)
        state={'last_order_at':last.isoformat()};api=self.cycle_api()
        with patch.object(bot,'read_state',return_value=state),patch.object(bot,'save_state'),patch.object(bot,'update_dashboard_snapshot'),patch.object(bot,'update_dashboard_schedule'),patch.object(bot,'local_now',return_value=now.astimezone(bot.ZoneInfo('Europe/Berlin'))):
            bot.run_once(api,self.settings,300,schedule_only=True)
            expected=state['schedule']['dueAt']
            state['schedule']['fingerprint']=state['schedule']['fingerprint'][1:]
            state['schedule']['dueAt']=(now+timedelta(days=1)).isoformat()
            bot.run_once(api,self.settings,300,schedule_only=True)
        self.assertEqual(state['schedule']['dueAt'],expected)

    def test_monthly_state_reset_preserves_last_purchase_anchor(self):
        path=self.root/'state.json'
        path.write_text(json.dumps({'cycle':'2026-09-01','spent':'50','last_order_at':'2026-09-30T12:00:00+00:00','last_order_quote':'8.02','deposit_tracking':{'dueAt':'2026-10-01T00:00:00+00:00'},'schedule':{'dueAt':'2026-10-01T00:00:00+00:00'}}))
        state=bot.read_state(path,'2026-10-01')
        self.assertEqual(state['spent'],'0')
        self.assertEqual(state['last_order_at'],'2026-09-30T12:00:00+00:00')
        self.assertEqual(state['last_order_quote'],'8.02')
        self.assertEqual(state['deposit_tracking']['dueAt'],'2026-10-01T00:00:00+00:00')
        self.assertEqual(state['schedule']['dueAt'],state['deposit_tracking']['dueAt'])

    def test_worker_enqueues_without_waiting_for_slow_account_cycle(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        def cycle():entered.set();release.wait(2);return 100
        def action(*args):finished.set();return {'token':'preview'}
        account=worker.Worker(cycle,action,100)
        with patch.object(worker,'HEALTH_PATH',self.root/'health.json'):
            account.start();self.assertTrue(entered.wait(1))
            begin=time.monotonic();job=account.submit('preview','owner')
            self.assertLess(time.monotonic()-begin,.2)
            with self.assertRaises(ValueError):account.get_job(job['jobId'],'different-session')
            self.assertEqual(account.get_job(job['jobId'],'owner')['state'],'queued')
            release.set();self.assertTrue(finished.wait(2))
            account.stop.set();account.thread.join(2)
            self.assertFalse(account.thread.is_alive())
            self.assertFalse(healthcheck.healthy(self.root/'health.json'))

    def test_worker_retries_failed_cycle_instead_of_silently_stopping(self):
        succeeded=threading.Event();calls=[]
        def cycle():
            calls.append(1)
            if len(calls)==1:raise ValueError('corrupt input')
            succeeded.set();return 100
        account=worker.Worker(cycle,Mock(),.01)
        with patch.object(worker,'HEALTH_PATH',self.root/'health.json'):
            account.start();self.assertTrue(succeeded.wait(2));self.assertEqual(len(calls),2)
            account.stop.set();account.thread.join(2)


class FinalPurchaseBudgetTests(unittest.TestCase):
    def test_last_order_absorbs_residual_and_reserves_fee_within_precision(self):
        from app.core.planning import plan_order
        market=dict(minOrderInBaseAsset='.00006',minOrderInQuoteAsset='0',quantityDecimals=8,notionalDecimals=2)
        plan=plan_order(market,D('.00006'),D('70000'),D('.0025'),D('4.6605'))
        self.assertEqual(plan.affordable,1)
        self.assertGreater(plan.quantity,plan.base_quantity)
        self.assertTrue(plan.remaining_budget)
        self.assertLessEqual(plan.cost,D('4.6605'))
        self.assertLess(D('4.6605')-plan.cost,D('.02'))
        # Earlier orders retain the configured BTC quantity.
        earlier=plan_order(market,D('.00006'),D('70000'),D('.0025'),D('20'))
        self.assertEqual(earlier.quantity,D('.00006'))
        self.assertFalse(earlier.remaining_budget)
        unfunded=plan_order(market,D('.00006'),D('70000'),D('.0025'),D('.45'))
        self.assertEqual(unfunded.affordable,0)

    def test_invalid_exchange_values_cannot_produce_an_executable_plan(self):
        from app.core.planning import plan_order
        market=dict(minOrderInBaseAsset='.00006',minOrderInQuoteAsset='0',quantityDecimals=8,notionalDecimals=2)
        for price in ['0','NaN','Infinity','-1']:
            with self.subTest(price=price),self.assertRaises(ValueError):
                plan_order(market,'0',price,'.0025','10')
        for places in [-1,19,True]:
            with self.subTest(places=places),self.assertRaises(ValueError):
                plan_order({**market,'quantityDecimals':places},'0','70000','.0025','10')


if __name__=='__main__':unittest.main()
