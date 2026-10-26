"""Compatibility launcher; runtime context also advertises the canonical tool."""
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode=True
for parent in Path(__file__).resolve().parents:
    tool=parent/'tools/music_tool.py'
    if tool.is_file() and tool.resolve()!=Path(__file__).resolve() and (parent/'config.default.json').is_file():
        runpy.run_path(str(tool),run_name='__main__')
        break
else:
    raise SystemExit('請使用 app 能力摘要提供的 canonical music_tool.py 路徑。')
