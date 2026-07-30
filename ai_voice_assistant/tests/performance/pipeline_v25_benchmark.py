from __future__ import annotations

import argparse
import gc
import json
import statistics
import threading
import time
import tracemalloc

import numpy as np

from core.audio_player import PlaybackChunk, AudioPlayer
from core.pipeline.messages import TurnSource
from core.pipeline.runtime import (
    PipelineRuntime,
    PipelineSettings,
    RuntimeMode,
    RuntimeSelection,
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def run_benchmark(turns: int = 200, warmup_turns: int = 20) -> dict:
    turns = max(1, int(turns))
    warmup_turns = max(0, int(warmup_turns))
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )
    player = AudioPlayer(
        sample_rate=24000,
        blocksize=32,
        max_queue_chunks=8,
        queue_put_timeout_seconds=0.0,
    )
    pcm = np.ones(32, dtype=np.int16)
    outdata = np.zeros((32, 1), dtype=np.int16)
    sources = (
        TurnSource.VOICE,
        TurnSource.TEXT,
        TurnSource.HEARTBEAT,
        TurnSource.SCHEDULE,
    )

    for index in range(warmup_turns):
        started = runtime.begin_turn(sources[index % len(sources)])
        runtime.complete(started.lease.context.turn_id)

    gc.collect()
    threads_before = threading.active_count()
    tracemalloc.start()
    memory_before = tracemalloc.get_traced_memory()[0]
    overhead_ms: list[float] = []
    stale_attempts = 0
    stale_audio_accepted = 0

    for index in range(turns):
        started_at = time.perf_counter()
        started = runtime.begin_turn(
            sources[index % len(sources)],
            request_id=f"benchmark-{index}",
        )
        lease = started.lease
        generation = int(lease.context.response_generation)
        player.set_response_generation(generation)

        if index and index % 10 == 0:
            stale_attempts += 1
            stale_audio_accepted += int(
                player.play(
                    PlaybackChunk(
                        pcm_data=pcm,
                        response_generation=generation - 1,
                        turn_id="stale-turn",
                    )
                )
            )

        accepted = player.play(
            PlaybackChunk(
                pcm_data=pcm,
                response_generation=generation,
                turn_id=lease.context.turn_id,
            )
        )
        if not accepted:
            raise AssertionError("Current-generation audio was rejected")
        outdata.fill(0)
        player._output_callback(outdata, 32, None, None)
        if not np.any(outdata):
            raise AssertionError("Current-generation audio was not rendered")
        runtime.complete(lease.context.turn_id)
        overhead_ms.append((time.perf_counter() - started_at) * 1000.0)

    memory_after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    gc.collect()
    threads_after = threading.active_count()

    player.set_response_generation(runtime.response_generation + 1)
    player.play(
        PlaybackChunk(
            pcm_data=pcm,
            response_generation=player.response_generation,
            turn_id="interrupt-probe",
        )
    )
    cancel_requested_at = time.monotonic()
    player.interrupt()
    try:
        player._output_callback(outdata, 32, None, None)
    except Exception:
        # sounddevice.CallbackStop is the expected callback termination signal.
        pass
    software_silent_at = player.software_silent_at or time.monotonic()
    interruption_to_silence_ms = max(
        0.0,
        (software_silent_at - cancel_requested_at) * 1000.0,
    )

    sample_window = max(1, turns // 4)
    first_window = overhead_ms[:sample_window]
    last_window = overhead_ms[-sample_window:]
    first_p95 = _percentile(first_window, 0.95)
    last_p95 = _percentile(last_window, 0.95)
    # Sub-millisecond Windows scheduler jitter dominates this in-process fake
    # benchmark, so use a documented 1 ms denominator floor. Real acoustic and
    # backend benchmarks keep their native durations and do not use this floor.
    drift_noise_floor_ms = 1.0
    raw_drift_pct = (
        ((last_p95 - first_p95) / first_p95) * 100.0 if first_p95 else 0.0
    )
    material_drift_ms = max(0.0, last_p95 - first_p95 - drift_noise_floor_ms)
    drift_pct = (
        material_drift_ms / max(first_p95, drift_noise_floor_ms)
    ) * 100.0
    diagnostics = runtime.diagnostic_snapshot()
    runtime.close()

    return {
        "scenario": "fake_backend_pipeline",
        "turns": turns,
        "warmup_turns": warmup_turns,
        "pipeline_overhead_ms": {
            "p50": round(statistics.median(overhead_ms), 4),
            "p95": round(_percentile(overhead_ms, 0.95), 4),
            "max": round(max(overhead_ms), 4),
            "first_window_p95": round(first_p95, 4),
            "last_window_p95": round(last_p95, 4),
            "drift_pct": round(drift_pct, 2),
            "raw_drift_pct": round(raw_drift_pct, 2),
            "drift_noise_floor_ms": drift_noise_floor_ms,
        },
        "interruption_to_software_silence_ms": round(interruption_to_silence_ms, 4),
        "queue": {
            "capacity": player.max_queue_chunks,
            "high_watermark": player.queue_high_watermark,
            "overflow_count": player.queue_overflow_count,
        },
        "generation_filter": {
            "stale_attempts": stale_attempts,
            "stale_audio_accepted": stale_audio_accepted,
            "stale_chunks_dropped": player.stale_chunk_drop_count,
        },
        "resources": {
            "thread_delta": threads_after - threads_before,
            "traced_memory_delta_bytes": memory_after - memory_before,
            "retained_trace_count": diagnostics["retained_trace_count"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=200)
    parser.add_argument("--warmup-turns", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(
            run_benchmark(args.turns, args.warmup_turns),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
