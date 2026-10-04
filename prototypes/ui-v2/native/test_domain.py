import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from domain import SessionConfig, SessionController, Phase, HtmlBudget, TAIPEI
from services import DemoTurnService

def config(**kwargs):
    return SessionConfig('codex_cli','demo-model','medium',**kwargs)

class ControllerTests(unittest.TestCase):
    def test_fixed_text_is_locked(self):
        c=SessionController(config(voice_input=False,voice_output=False))
        self.assertEqual(c.toggle_mic(),'locked')
        self.assertEqual(c.toggle_speaker(),'locked')
        self.assertTrue(c.mic_muted)

    def test_auto_mute_does_not_change_manual_mute(self):
        c=SessionController(config());c.phase=Phase.SPEAKING
        self.assertTrue(c.mic_muted)
        c.finish(0);self.assertFalse(c.mic_muted)
        c.manual_mute=True;c.phase=Phase.SPEAKING;c.finish(0)
        self.assertTrue(c.mic_muted)

    def test_microphone_interrupt_reserves_capture_before_queue(self):
        c=SessionController(config());c.phase=Phase.SPEAKING;c.enqueue('wait')
        self.assertEqual(c.toggle_mic(),'interrupt')
        self.assertEqual(c.phase,Phase.LISTENING)
        self.assertIsNone(c.take_next())
        self.assertFalse(c.mic_muted)

    def test_fifo_cancel_and_busy(self):
        c=SessionController(config());c.enqueue('one');c.enqueue('two');c.enqueue('three')
        c.cancel_pending(2)
        first,generation=c.take_next()
        self.assertEqual(first.text,'one');self.assertIsNone(c.take_next())
        c.finish(generation)
        self.assertEqual(c.take_next()[0].text,'three')

    def test_stale_completion_cannot_finish_new_turn(self):
        c=SessionController(config());c.enqueue('one');_,old=c.take_next()
        c.interrupt();c.enqueue('two');_,current=c.take_next()
        self.assertFalse(c.finish(old));self.assertEqual(c.phase,Phase.THINKING)
        self.assertTrue(c.finish(current))

    def test_capacity_preserves_existing_queue(self):
        c=SessionController(config())
        self.assertFalse(c.enqueue('  '))
        for _ in range(10): c.enqueue('hello')
        with self.assertRaises(ValueError): c.enqueue('overflow')
        self.assertEqual(len(c.pending),10)

    def test_muting_speaker_does_not_interrupt_generation(self):
        c=SessionController(config());c.enqueue('hi');_,generation=c.take_next()
        c.toggle_speaker()
        self.assertEqual(c.phase,Phase.THINKING)
        self.assertEqual(c.generation,generation)

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'quota.json'
        self.wall=datetime(2026,10,4,12,tzinfo=TAIPEI);self.mono=0
        self.budget=HtmlBudget(self.path,30,lambda:self.wall,lambda:self.mono)

    def advance(self,seconds,charge):
        self.mono+=seconds;self.wall+=timedelta(seconds=seconds)
        return self.budget.tick(charge)

    def test_hidden_and_non_html_do_not_charge(self):
        self.advance(5,True);self.advance(40,False)
        self.assertEqual(self.budget.remaining,25)

    def test_persisted_usage_survives_restart_and_lower_limit(self):
        self.advance(12,True);self.budget.save()
        reload=HtmlBudget(self.path,10,lambda:self.wall,lambda:self.mono)
        self.assertEqual(reload.remaining,0);self.assertEqual(reload.used,12)

    def test_cross_midnight_only_charges_new_day_part(self):
        self.wall=datetime(2026,10,4,23,59,58,tzinfo=TAIPEI)
        self.budget.tick(False)
        self.advance(5,True)
        self.assertEqual(self.budget.day,'2026-10-05')
        self.assertEqual(self.budget.used,3)

    def test_clock_rollback_does_not_replenish(self):
        self.advance(10,True)
        self.wall-=timedelta(days=2);self.mono+=5;self.budget.tick(True)
        self.assertEqual(self.budget.day,'2026-10-04');self.assertEqual(self.budget.used,15)

    def test_bad_persistence_fails_closed(self):
        self.path.write_text('{invalid',encoding='utf-8')
        with self.assertRaises(ValueError): HtmlBudget(self.path,30)

class Scheduler:
    def __init__(self): self.jobs={};self.index=0
    def after(self,ms,callback):
        self.index+=1;self.jobs[self.index]=callback;return self.index
    def after_cancel(self,job): self.jobs.pop(job,None)
    def run_next(self):
        ident=min(self.jobs);self.jobs.pop(ident)()

class ServiceTests(unittest.TestCase):
    def test_generation_and_playback_are_separate_and_mute_drains(self):
        scheduler=Scheduler();events=[]
        service=DemoTurnService(scheduler,lambda:True)
        service.start('test',lambda kind,text:events.append(kind))
        scheduler.run_next()
        self.assertEqual(events,['text','generation_done','playback_started'])
        service.mute_output()
        self.assertEqual(events[-1],'playback_done');self.assertFalse(scheduler.jobs)

    def test_cancel_removes_all_pending_callbacks(self):
        scheduler=Scheduler();events=[]
        service=DemoTurnService(scheduler,lambda:True)
        service.start('test',lambda *args:events.append(args));service.cancel()
        self.assertFalse(scheduler.jobs);self.assertFalse(events)

if __name__=='__main__': unittest.main()
