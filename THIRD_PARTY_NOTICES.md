# Third-Party Notices

Runtime dependencies are listed in `ai_voice_assistant/requirements.txt`.

Current direct dependencies are primarily MIT, BSD, Apache-2.0, and LGPL-family packages. Pay special attention to:

- `edge-tts`: LGPLv3 classifier in package metadata.
- `pynput`: LGPLv3 in package metadata.
- `torch` / `torchaudio`: large binary packages with their own notices.
- NVIDIA CUDA wheels pulled by some ML stacks: proprietary runtime components; do not commit `venv/` or bundled DLLs.
- `sherpa-onnx` and the default wake-word model: check the package and model license before redistributing binaries.

This repository should not vendor Python packages, wheels, virtual environments, or downloaded model artifacts.

## Silero VAD iterator

`ai_voice_assistant/core/vad.py` contains a streaming VAD iterator adapted from
`silero-vad` 6.2.1 (`src/silero_vad/utils_vad.py`):
https://github.com/snakers4/silero-vad/blob/v6.2.1/src/silero_vad/utils_vad.py

MIT License

Copyright (c) 2020-present Silero Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
