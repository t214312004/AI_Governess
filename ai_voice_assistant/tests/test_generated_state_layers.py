from types import SimpleNamespace

from PIL import Image
import pytest

from tools import build_generated_state_layers as builder


def test_invalid_column_count_preserves_existing_layers(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (14, 10), "green").save(source)
    output_dir = tmp_path / "layers"
    output_dir.mkdir()
    background = output_dir / "background.png"
    background.write_bytes(b"existing background")
    monkeypatch.setattr(builder, "DIAGNOSTICS_DIR", tmp_path / "diagnostics")
    monkeypatch.setattr(builder, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(builder, "parse_args", lambda: SimpleNamespace(
        version="test", background_source=source, sprite_source=source,
        state_strip_source=[], output_dir=output_dir, preview=False, source_columns=6,
    ))

    with pytest.raises(SystemExit, match="at least 7"):
        builder.main()

    assert background.read_bytes() == b"existing background"
