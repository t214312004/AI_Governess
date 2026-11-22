"""Methodology checks for the offline GPU archive comparison."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('archive_benchmark', Path(__file__).parents[2] / 'scripts/benchmark_asr_archive_gpu.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_stratified_selection_is_repeatable_unique_and_covers_challenges():
    rows = []
    for i in range(100):
        rows.append({'file': f'{i:03}.wav', 'audio_seconds': 2 if i < 20 else 40 if i < 40 else 8,
                     'historical_asr': '' if 40 <= i < 50 else '(聲音雜亂, 系統無法辨識)' if 50 <= i < 60
                     else 'Python 測試' if 60 <= i < 80 else '一般內容'})
    selected = benchmark.select_samples(rows, 40)
    assert selected == benchmark.select_samples(rows, 40)
    assert len(selected) == len({row['file'] for row in selected}) == 40
    assert {'short', 'long', 'recent', 'historical_latin', 'historical_empty',
            'historical_noise_placeholder'} <= {row['selection_category'] for row in selected}
    assert all('selection_category' not in row for row in rows)


def test_small_archive_does_not_duplicate_samples():
    rows = [{'file': 'one.wav', 'audio_seconds': 5, 'historical_asr': '測試'}]
    assert len(benchmark.select_samples(rows, 40)) == 1


def test_normalization_ignores_formatting_but_preserves_meaning_and_script():
    assert benchmark.normalized('Ｐｙｔｈｏｎ，測試。') == benchmark.normalized('python 測試')
    assert benchmark.normalized('不要刪除') != benchmark.normalized('要刪除')
    assert benchmark.normalized('請開燈') != benchmark.normalized('请开灯')


def test_percentile_interpolates_and_handles_single_sample():
    assert benchmark.percentile([3], .95) == 3
    assert benchmark.percentile([1, 2, 3, 4, 5], .95) == pytest.approx(4.8)


@pytest.mark.parametrize('invalid', ['missing', 'duplicate', 'wrong_mode'])
def test_incomplete_or_duplicate_runs_cannot_produce_successful_summary(invalid):
    manifest = {'samples': [{'file': 'one.wav'}], 'models': ['breeze'],
                'breeze_languages': ['auto'], 'repeats': 2}
    rows = [{'file': 'one.wav', 'mode': 'breeze_auto', 'repeat': r} for r in (0, 1)]
    benchmark.validate_runs(manifest, rows)
    if invalid == 'missing':
        rows.pop()
    elif invalid == 'duplicate':
        rows.append(dict(rows[0]))
    else:
        rows[0]['mode'] = 'whisper_v1_auto'
    with pytest.raises(ValueError, match='Incomplete or duplicate'):
        benchmark.validate_runs(manifest, rows)


def test_report_escapes_transcripts_and_uses_local_audio_links(tmp_path):
    sample = {'file': 'sample.wav', 'audio_seconds': 3, 'selection_category': 'general',
              'historical_asr': '<img src=x onerror=alert(1)>'}
    first = {('sample.wav', 'breeze_auto'): {'raw_text': '<script>bad()</script>',
                                          'elapsed_seconds': .4, 'detected_language': 'zh'}}
    stats = {'breeze_auto': {'p50_seconds': .4, 'p95_seconds': .5, 'weighted_rtf': .1}}
    benchmark.render_html(tmp_path, {'archive': str(tmp_path / 'audio'), 'samples': [sample]}, first, stats)
    page = (tmp_path / 'comparison.html').read_text(encoding='utf-8')
    assert '<img src=x' not in page and '<script>bad()' not in page
    assert '&lt;script&gt;bad()&lt;/script&gt;' in page
    assert 'src="audio/sample.wav"' in page
    assert '非人工正解' in page
