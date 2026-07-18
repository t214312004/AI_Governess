import pytest
from llm.semantic_chunker import SemanticChunker

def test_init_defaults():
    chunker = SemanticChunker()
    assert chunker.buffer == ""
    assert "。" in chunker.split_punctuation

def test_init_custom():
    chunker = SemanticChunker(split_punctuation="。", also_split="")
    assert chunker.split_punctuation == set("。")

def test_add_token_splits_on_punctuation():
    chunker = SemanticChunker()
    tokens = ["你好", "，", "我是", "愛管家", "。"]
    results = []
    for t in tokens:
        results.extend(list(chunker.add_token(t)))
    assert len(results) >= 1
    assert "你好，我是愛管家。" in "".join(results) or results[0] == "你好，我是愛管家。"

def test_add_token_multi_sentence():
    chunker = SemanticChunker()
    tokens = ["第一句。", "第二句！", "第三句？"]
    results = []
    for t in tokens:
        results.extend(list(chunker.add_token(t)))
    assert results == ["第一句。", "第二句！", "第三句？"]

def test_add_token_filter_meaningless_punctuations():
    """Verify Bug-3 fix: chunks without alphanumeric/chinese characters are filtered out."""
    chunker = SemanticChunker()
    assert list(chunker.add_token("……。")) == []
    assert list(chunker.add_token("！！？")) == []
    assert list(chunker.add_token("你好。")) == ["你好。"]

def test_add_token_strip_whitespace():
    """Verify that chunks are stripped of leading/trailing whitespace."""
    chunker = SemanticChunker()
    results = list(chunker.add_token("  這是一句話。  "))
    assert results == ["這是一句話。"]

def test_flush_returns_remaining_if_valid():
    chunker = SemanticChunker()
    _ = list(chunker.add_token("這是沒說完的話"))
    results = list(chunker.flush())
    assert results == ["這是沒說完的話"]
    assert chunker.buffer == ""

def test_flush_empty_or_invalid_buffer():
    """flush() on empty or meaningless buffer should yield nothing."""
    chunker = SemanticChunker()
    assert list(chunker.flush()) == []

    _ = list(chunker.add_token("……"))
    assert list(chunker.flush()) == []

def test_reset_clears_buffer():
    """BUG-1/O-7 fix: reset() should clear buffer to prevent cross-conversation residue."""
    chunker = SemanticChunker()
    _ = list(chunker.add_token("未完成的"))
    assert chunker.buffer == "未完成的"
    chunker.reset()
    assert chunker.buffer == ""

def test_reset_after_flush_is_idempotent():
    """reset() on an already-empty buffer is safe."""
    chunker = SemanticChunker()
    chunker.reset()
    chunker.reset()
    assert chunker.buffer == ""

def test_multiple_chunks_in_single_token():
    """A single token containing multiple punctuation marks yields multiple chunks."""
    chunker = SemanticChunker()
    results = list(chunker.add_token("一。二。三。"))
    assert results == ["一。", "二。", "三。"]


def test_rare_traditional_cjk_character_is_not_dropped():
    chunker = SemanticChunker()

    assert list(chunker.add_token("龜。")) == ["龜。"]


