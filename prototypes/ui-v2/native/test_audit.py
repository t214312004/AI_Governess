"""Regression tests for confirmed audit defects and failure boundaries."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from domain import HtmlBudget, Phase, SessionConfig, SessionController
from services import DemoTurnService, ModelInfo
from test_domain import Scheduler
from validation import parse_field, session_snapshot, validate_settings

DEFAULTS = Path(__file__).resolve().parents[3] / 'ai_voice_assistant/config.default.json'


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.defaults = json.loads(DEFAULTS.read_text(encoding='utf-8'))

    def test_default_settings_validate(self):
        self.assertEqual(validate_settings(self.defaults,self.defaults), self.defaults)

    def test_nonfinite_and_invalid_numeric_inputs_rejected(self):
        for value in ('NaN','inf','-inf'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_field(value,1.0)
        self.defaults['ui']['animation_interval_ms'] = 0
        with self.assertRaises(ValueError): validate_settings(self.defaults,self.defaults)

    def test_session_selections_replace_backend_and_shortcuts(self):
        cfg = SessionConfig('codex_cli','queried-model','high')
        result = session_snapshot(self.defaults,cfg)
        self.assertEqual(result['llm']['active_backend'],'codex_cli')
        self.assertEqual(result['llm']['codex_cli']['model'],'queried-model')
        self.assertEqual(result['llm']['codex_cli']['reasoning_effort'],'high')
        self.assertEqual(result['ui']['fullscreen_exit_shortcuts'],['ALT+F4'])
        self.assertEqual(result['ui']['fullscreen_enter_shortcuts'],[])
        self.assertEqual(self.defaults['llm']['active_backend'],'antigravity_cli')

    def test_session_rejects_wrong_types_and_font(self):
        for kwargs in ({'html_minutes':True},{'html_minutes':3.5},{'voice_input':'true'},{'chat_font':1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SessionConfig('backend','model','effort',**kwargs)

    def test_catalog_rejects_malformed_models(self):
        for args in (('',()),('model',['low']),('model',('low','low')),('model',(1,))):
            with self.subTest(args=args), self.assertRaises(ValueError): ModelInfo(*args)


class BudgetFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'quota.json'

    def test_invalid_records_rejected_even_on_old_day(self):
        cases=[[],{}, {'day':None,'used':0},{'day':'1900-01-01','used':-1},
               {'day':'20261004','used':0},{'day':'2026-10-04','used':True},
               {'day':'2026-10-04','used':'10'},{'day':'2026-10-04','used':math.inf}]
        for data in cases:
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(ValueError): HtmlBudget(self.path,30)

    def test_invalid_limit_rejected(self):
        for value in (-1,math.nan,math.inf,True,'30',86401,10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError): HtmlBudget(self.path,value)

    def test_failed_replace_retains_previous_file_and_cleans_temp(self):
        budget=HtmlBudget(self.path,30);budget.save()
        before=self.path.read_bytes();budget.used=10
        with patch('domain.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): budget.save()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')),[])
        budget.save()
        self.assertEqual(json.loads(self.path.read_text())['used'],10)


class CancellationTests(unittest.TestCase):
    def test_duplicate_completion_cannot_end_capture(self):
        controller=SessionController(SessionConfig('b','m','e'))
        controller.phase=Phase.LISTENING
        self.assertFalse(controller.finish(controller.generation))
        self.assertEqual(controller.phase,Phase.LISTENING)

    def test_cancel_during_callback_cannot_restart_playback(self):
        scheduler=Scheduler();events=[]
        service=DemoTurnService(scheduler,lambda:True)
        def event(kind,payload):
            events.append(kind)
            if kind=='generation_done': service.cancel()
        service.start('hello',event);scheduler.run_next()
        self.assertEqual(events,['text','generation_done'])
        self.assertFalse(scheduler.jobs)

    def test_queued_stale_timer_cannot_complete_new_turn(self):
        scheduler=Scheduler();old=[];current=[]
        service=DemoTurnService(scheduler,lambda:True)
        service.start('old',lambda *args:old.append(args))
        stale=next(iter(scheduler.jobs.values()))
        service.start('new',lambda *args:current.append(args));stale()
        self.assertFalse(old);self.assertFalse(current)
        scheduler.run_next()
        self.assertEqual(current[-1][0],'playback_started')


if __name__=='__main__': unittest.main()
