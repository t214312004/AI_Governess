"""Isolate the preview before importing production UI components."""
import os
import atexit
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'ai_voice_assistant'
NATIVE = Path(__file__).resolve().parent
RUNTIME = NATIVE / '.runtime'
sys.dont_write_bytecode = True
sys.path.insert(0, str(APP))
# Only this process is affected. No private config, production logs or pyc writes.
_config_isolation = TemporaryDirectory(prefix='governess-demo-config-')
atexit.register(_config_isolation.cleanup)
os.environ['AI_GOVERNESS_CONFIG'] = str(Path(_config_isolation.name) / 'unused-config.json')
os.environ['AI_GOVERNESS_DISABLE_LOGGING'] = '1'
