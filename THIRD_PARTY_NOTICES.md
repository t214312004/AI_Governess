# Third-Party Notices

Runtime dependencies are listed in `ai_voice_assistant/requirements.txt`.

Current direct dependencies are primarily MIT, BSD, Apache-2.0, and LGPL-family packages. Pay special attention to:

- `edge-tts`: LGPLv3 classifier in package metadata.
- `pynput`: LGPLv3 in package metadata.
- `torch` / `torchaudio`: large binary packages with their own notices.
- NVIDIA CUDA wheels pulled by some ML stacks: proprietary runtime components; do not commit `venv/` or bundled DLLs.
- `sherpa-onnx` and the default wake-word model: check the package and model license before redistributing binaries.

This repository should not vendor Python packages, wheels, virtual environments, or downloaded model artifacts.
