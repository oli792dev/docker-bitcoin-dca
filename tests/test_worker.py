"""Offline regression coverage grouped by worker scheduling and health."""
import unittest
from unittest.mock import Mock, patch
from app.trading import worker
import queue
from unittest import TestCase


class HeartbeatTests(unittest.TestCase):
    def test_first_write_is_immediate_and_subsequent_writes_are_five_minutes_apart(self):
        account=worker.Worker(Mock(),Mock(),300)
        account.running=True
        with patch.object(worker,'write_json_atomic') as write,patch.object(worker.time,'time',return_value=1000):
            with patch.object(worker.time,'monotonic',return_value=0):account.heartbeat()
            self.assertEqual(write.call_count,1)
            with patch.object(worker.time,'monotonic',return_value=299):account.heartbeat()
            self.assertEqual(write.call_count,1)
            self.assertEqual(account.beat,299)
            with patch.object(worker.time,'monotonic',return_value=300):account.heartbeat()
            self.assertEqual(write.call_count,2)
            self.assertTrue(write.call_args.args[1]['running'])

    def test_stop_is_persisted_immediately_without_waiting_for_next_write_interval(self):
        account=worker.Worker(Mock(),Mock(),300)
        account.stop.set()
        with patch.object(worker,'write_json_atomic') as write:account.run()
        self.assertEqual(write.call_count,1)
        self.assertFalse(write.call_args.args[1]['running'])

    def test_ten_minute_stall_threshold_is_preserved(self):
        account=worker.Worker(Mock(),Mock(),300)
        account.running=True;account.beat=100
        with patch.object(worker.time,'monotonic',return_value=699):self.assertTrue(account.healthy())
        with patch.object(worker.time,'monotonic',return_value=700):self.assertFalse(account.healthy())


class PreviewCheckTimingTests(TestCase):
    def test_manual_withdrawals_preserve_the_next_check(self):
        for action,expected_checks in [("preview",1),("confirm",1)]:
            with self.subTest(action=action):
                clock=[100.0]
                with patch.object(worker.time,"monotonic",side_effect=lambda:clock[0]),patch.object(worker,"write_json_atomic"):
                    cycle=Mock(return_value=300)
                    w=worker.Worker(cycle,Mock(return_value={"ok":True}),300)
                    w.jobs["job"]={"state":"queued"}
                    calls=[0]
                    def get(timeout):
                        calls[0]+=1
                        if calls[0]==1:raise queue.Empty
                        if calls[0]==2:return ("job",action,"session",None)
                        clock[0]=102.0
                        w.stop.set()
                        raise queue.Empty
                    w.queue=Mock();w.queue.get.side_effect=get;w.queue.get_nowait.side_effect=queue.Empty
                    w.run()
                    self.assertEqual(cycle.call_count,expected_checks)
                    w.action.assert_called_once_with(action,"session",None)
                    self.assertEqual(w.jobs["job"]["state"],"completed")


class WorkerLifecycleTests(TestCase):
    def test_due_checks_run_even_with_continuously_queued_manual_requests(self):
        clock=[100.0];checks=[];actions=[]
        account=worker.Worker(lambda:checks.append(clock[0]) or 2,None,300)
        account.running=True
        for _ in range(5):account.submit('preview','owner')
        def action(*args):
            actions.append(clock[0]);clock[0]+=1
            if len(actions)==5:account.stop.set()
            return {}
        account.action=action
        with patch.object(worker.time,'monotonic',side_effect=lambda:clock[0]),patch.object(worker,'write_json_atomic'):
            account.run()
        self.assertEqual(checks,[100.0,102.0,104.0])
        self.assertEqual(len(actions),5)
        self.assertEqual(account.queue.unfinished_tasks,0)

    def test_stop_finishes_active_action_and_cancels_queued_actions(self):
        import threading
        started=threading.Event();release=threading.Event();finished=threading.Event()
        def action(*args):started.set();release.wait(2);finished.set();return {'ok':True}
        account=worker.Worker(Mock(return_value=300),action,300)
        with patch.object(worker,'write_json_atomic'):
            account.start();first=account.submit('preview','owner')
            self.assertTrue(started.wait(1))
            second=account.submit('confirm','owner','token')
            self.assertFalse(account.shutdown(timeout=0))
            self.assertFalse(finished.is_set())
            with self.assertRaisesRegex(ValueError,'unavailable'):account.submit('preview','owner')
            release.set();self.assertTrue(account.shutdown(timeout=2))
        self.assertTrue(finished.is_set())
        self.assertEqual(account.get_job(first['jobId'],'owner')['state'],'completed')
        self.assertEqual(account.get_job(second['jobId'],'owner')['state'],'failed')
        self.assertEqual(account.queue.unfinished_tasks,0)

    def test_sigterm_requests_coordinated_stop_and_restores_handlers(self):
        import subprocess,sys
        script="""import os,signal,threading
from types import SimpleNamespace
from app.core.lifecycle import shutdown_signals
worker=SimpleNamespace(stop=threading.Event())
previous=signal.getsignal(signal.SIGTERM)
with shutdown_signals(worker) as stop:
 os.kill(os.getpid(),signal.SIGTERM)
 assert stop.is_set() and worker.stop.is_set()
assert signal.getsignal(signal.SIGTERM)==previous
"""
        subprocess.run([sys.executable,'-c',script],check=True,timeout=5)


class WorkerErrorTests(TestCase):
    def test_unexpected_job_details_stay_out_of_browser_responses(self):
        import requests
        for error in (RuntimeError('private internal detail'), requests.ReadTimeout('private request detail'), ValueError('Action unavailable')):
            with self.subTest(error=type(error).__name__):
                account=worker.Worker(Mock(),None,300)
                account.running=True
                job=account.submit('preview','owner')
                def action(*args):
                    account.stop.set()
                    raise error
                account.action=action
                with patch.object(worker,'write_json_atomic'),patch.object(worker.LOG,'exception'),patch.object(worker.LOG,'warning'),patch.object(worker.LOG,'info'):
                    account.run()
                result=account.get_job(job['jobId'],'owner')
                self.assertEqual(result['state'],'failed')
                if isinstance(error,ValueError):self.assertEqual(result['error'],'Action unavailable')
                else:self.assertNotIn('private',result['error'])


class WorkerJobRetentionTests(TestCase):
    def test_active_jobs_remain_visible_and_terminal_jobs_expire_from_finish(self):
        for error in (None, ValueError("Action unavailable")):
            with self.subTest(error=error):
                self._check_terminal_retention(error)

    def _check_terminal_retention(self, error):
        clock = Mock(return_value=100)
        account = worker.Worker(Mock(return_value=300), Mock(), 300)
        account.running = True

        with patch.object(worker.time, "monotonic", clock), patch.object(worker, "write_json_atomic"):
            active = account.submit("preview", "owner")["jobId"]
            queued = account.submit("confirm", "owner", "token")["jobId"]
            clock.return_value = 1100
            self.assertEqual(account.get_job(active, "owner"), {"state": "queued"})
            with self.assertRaises(ValueError):
                account.get_job(active, "different-session")

            def action(*args):
                account.stop.set()
                clock.return_value = 2100
                self.assertEqual(account.get_job(active, "owner"), {"state": "running"})
                self.assertEqual(account.get_job(queued, "owner"), {"state": "queued"})
                with self.assertRaises(ValueError):
                    account.get_job(active, "different-session")
                if error:
                    raise error
                return {"ok": True}

            account.action.side_effect = action
            account.run()

            clock.return_value = 2999
            expected = (
                {"state": "failed", "error": str(error)}
                if error
                else {"state": "completed", "result": {"ok": True}}
            )
            self.assertEqual(account.get_job(active, "owner"), expected)
            self.assertEqual(account.get_job(queued, "owner")["state"], "failed")
            clock.return_value = 3000
            for job_id in (active, queued):
                with self.assertRaises(ValueError):
                    account.get_job(job_id, "owner")

    def test_active_jobs_keep_their_queue_slots_and_expired_jobs_free_capacity(self):
        clock = Mock(return_value=100)
        account = worker.Worker(Mock(return_value=300), Mock(return_value={}), 100_000)
        account.running = True

        with patch.object(worker.time, "monotonic", clock), patch.object(worker, "write_json_atomic"):
            first = account.submit("preview", "owner")["jobId"]
            for _ in range(15):
                account.submit("preview", "owner")
            clock.return_value = 1100
            with self.assertRaisesRegex(ValueError, "busy"):
                account.submit("preview", "owner")
            self.assertEqual(len(account.jobs), 16)
            self.assertEqual(account.get_job(first, "owner"), {"state": "queued"})

            admitted_after_expiry = []

            def fill_job_history(*args):
                if len(account.jobs) < 128:
                    account.submit("preview", "owner")
                else:
                    try:
                        with self.assertRaisesRegex(ValueError, "Too many"):
                            account.submit("preview", "owner")
                        clock.return_value += 900
                        admitted_after_expiry.append(account.submit("preview", "owner"))
                    finally:
                        account.stop.set()
                return {}

            account.action.side_effect = fill_job_history
            account.run()
            self.assertEqual(len(admitted_after_expiry), 1)
            self.assertEqual(account.queue.unfinished_tasks, 0)

    def test_job_dequeued_during_shutdown_expires_from_cancellation(self):
        clock = Mock(return_value=100)
        account = worker.Worker(Mock(return_value=300), Mock(), 300)
        account.running = True
        get = account.queue.get

        def stop_on_get(*args, **kwargs):
            account.stop.set()
            return get(*args, **kwargs)

        with (
            patch.object(worker.time, "monotonic", clock),
            patch.object(worker, "write_json_atomic"),
            patch.object(account.queue, "get", side_effect=stop_on_get),
        ):
            job_id = account.submit("preview", "owner")["jobId"]
            clock.return_value = 1100
            account.run()
            account.action.assert_not_called()
            self.assertEqual(account.get_job(job_id, "owner")["state"], "failed")
            self.assertEqual(account.queue.unfinished_tasks, 0)
            clock.return_value = 2000
            with self.assertRaises(ValueError):
                account.get_job(job_id, "owner")
