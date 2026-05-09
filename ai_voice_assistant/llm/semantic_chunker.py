import re


class SemanticChunker:
    """
    Buffer streamed LLM tokens and emit full sentence-like chunks.

    This lets TTS speak sentence units instead of individual tokens.
    """

    def __init__(self, split_punctuation="。！？；", also_split=".!?;"):
        self.split_punctuation = set(split_punctuation + also_split)
        self.buffer = ""
        self.valid_pattern = re.compile(r"[a-zA-Z0-9\u4e00-\u9fa5]")

    def _split_buffer(self) -> str:
        """Return the first complete chunk currently in the buffer."""
        for i, char in enumerate(self.buffer):
            if char in self.split_punctuation:
                chunk = self.buffer[: i + 1]
                self.buffer = self.buffer[i + 1 :]
                return chunk

        return ""

    def add_token(self, token: str):
        """Add a token and yield complete chunks as they become available."""
        self.buffer += token
        while True:
            chunk = self._split_buffer()
            if chunk:
                if self.valid_pattern.search(chunk):
                    yield chunk.strip()
            else:
                break

    def flush(self):
        """Flush the remaining buffer as one chunk."""
        if self.buffer:
            chunk = self.buffer
            self.buffer = ""
            if self.valid_pattern.search(chunk):
                yield chunk.strip()

    def reset(self):
        """Clear buffered text before a new turn."""
        self.buffer = ""
