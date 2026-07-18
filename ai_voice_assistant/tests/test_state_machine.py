import time
import threading
import pytest
from core.state_machine import State, VoiceAssistantStateMachine

def test_initial_state():
    sm = VoiceAssistantStateMachine()
    assert sm.current_state == State.IDLE_LISTEN
    assert sm.hot_listen_timeout == 8.0

def test_current_state_property_thread_safe():
    """BUG-4 fix: current_state is now a thread-safe property backed by a Lock."""
    sm = VoiceAssistantStateMachine()

    for state in State:
        sm.transition(state)
        assert sm.current_state == state

def test_transition_all_states():
    sm = VoiceAssistantStateMachine()
    sm.transition(State.COLLECTING)
    assert sm.current_state == State.COLLECTING
    sm.transition(State.SENDING)
    assert sm.current_state == State.SENDING
    sm.transition(State.SPEAKING)
    assert sm.current_state == State.SPEAKING

def test_hot_listen_transition_starts_timer(mocker):
    sm = VoiceAssistantStateMachine()
    mock_time = mocker.patch("core.state_machine.time.monotonic")
    mock_time.return_value = 100.0
    sm.transition(State.HOT_LISTEN)
    assert sm.current_state == State.HOT_LISTEN
    assert sm._hot_listen_start_time == 100.0

def test_hot_listen_transition_and_timeout(mocker):
    sm = VoiceAssistantStateMachine()
    mock_time = mocker.patch("core.state_machine.time.monotonic")
    mock_time.return_value = 100.0

    sm.transition(State.HOT_LISTEN)
    assert sm.current_state == State.HOT_LISTEN


    mock_time.return_value = 107.0
    assert sm.check_hot_listen_timeout() is False
    assert sm.current_state == State.HOT_LISTEN


    mock_time.return_value = 108.1
    assert sm.check_hot_listen_timeout() is True
    assert sm.current_state == State.HOT_LISTEN

def test_check_hot_listen_timeout_returns_false_in_wrong_state():
    sm = VoiceAssistantStateMachine()
    sm.transition(State.COLLECTING)
    assert sm.check_hot_listen_timeout() is False
    assert sm.current_state == State.COLLECTING

def test_interrupt():
    sm = VoiceAssistantStateMachine()
    sm.transition(State.SPEAKING)
    previous = sm.interrupt()
    assert previous == State.SPEAKING
    assert sm.current_state == State.COLLECTING

def test_interrupt_from_sending():
    sm = VoiceAssistantStateMachine()
    sm.transition(State.SENDING)
    previous = sm.interrupt()
    assert previous == State.SENDING
    assert sm.current_state == State.COLLECTING

def test_interrupt_blocks_concurrent_transition_until_state_is_updated(mocker):
    sm = VoiceAssistantStateMachine()
    sm.transition(State.SPEAKING)
    transition_started = threading.Event()
    transition_done = threading.Event()
    spawned_thread = None

    def run_transition():
        transition_started.set()
        sm.transition(State.SENDING)
        transition_done.set()

    def log_side_effect(logger, level, event_name, **kwargs):
        nonlocal spawned_thread
        if event_name != "state.interrupt":
            return
        spawned_thread = threading.Thread(target=run_transition)
        spawned_thread.start()
        assert transition_started.wait(timeout=0.2)
        assert not transition_done.wait(timeout=0.02)
        assert sm._state == State.SPEAKING

    mocker.patch("core.state_machine.log_event", side_effect=log_side_effect)

    previous = sm.interrupt()

    assert previous == State.SPEAKING
    assert sm.current_state in (State.COLLECTING, State.SENDING)
    assert spawned_thread is not None
    spawned_thread.join(timeout=1)
    assert transition_done.is_set()

def test_thread_safety():
    """BUG-4: Concurrent transitions should not cause race conditions."""
    sm = VoiceAssistantStateMachine()
    errors = []

    def transition_loop(state):
        try:
            for _ in range(50):
                sm.transition(state)
                _ = sm.current_state
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=transition_loop, args=(State.COLLECTING,)),
        threading.Thread(target=transition_loop, args=(State.SENDING,)),
        threading.Thread(target=transition_loop, args=(State.SPEAKING,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread safety errors: {errors}"

