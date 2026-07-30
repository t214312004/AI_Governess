from tests.performance.pipeline_v25_benchmark import run_benchmark


def test_fake_backend_pipeline_survives_200_turns_with_bounded_resources():
    report = run_benchmark(turns=200, warmup_turns=20)

    assert report["pipeline_overhead_ms"]["p95"] < 75.0
    assert report["pipeline_overhead_ms"]["drift_pct"] <= 10.0
    assert report["interruption_to_software_silence_ms"] < 250.0
    assert report["queue"]["high_watermark"] <= report["queue"]["capacity"]
    assert report["queue"]["overflow_count"] == 0
    assert report["generation_filter"]["stale_audio_accepted"] == 0
    assert report["resources"]["thread_delta"] == 0
    assert report["resources"]["retained_trace_count"] <= 256
    assert report["resources"]["traced_memory_delta_bytes"] < 8 * 1024 * 1024
