from __future__ import annotations

from pathlib import Path

import private_state


APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parent


def test_public_html_whiteboard_demo_covers_supported_browser_features():
    demo = APP_DIR / "agent_workspace_template" / "apps" / "html_whiteboard_demo" / "index.html"
    source = demo.read_text(encoding="utf-8")

    assert "<canvas" in source
    assert "requestAnimationFrame" in source
    assert "addEventListener('keydown'" in source
    assert "pointerdown" in source
    assert "AudioContext" in source
    assert "localStorage" in source
    assert "viewport-fit=cover" in source
    assert "safe-area-inset-bottom" in source
    assert "http://" not in source
    assert "https://" not in source


def test_fresh_clone_bootstrap_copies_nested_public_demo(monkeypatch, tmp_path):
    template_root = tmp_path / "agent_workspace_template"
    workspace_root = tmp_path / "agent_workspace"
    demo = template_root / "apps" / "html_whiteboard_demo" / "index.html"
    demo.parent.mkdir(parents=True)
    demo.write_text("<!doctype html><canvas></canvas>", encoding="utf-8")
    monkeypatch.setattr(private_state, "AGENT_WORKSPACE_TEMPLATE_DIR", template_root)
    monkeypatch.setattr(private_state, "AGENT_WORKSPACE_DIR", workspace_root)
    monkeypatch.setattr(private_state, "PRIVATE_DIRS", (workspace_root,))

    private_state.ensure_private_state()

    copied = workspace_root / "apps" / "html_whiteboard_demo" / "index.html"
    assert copied.read_text(encoding="utf-8") == "<!doctype html><canvas></canvas>"


def test_public_documentation_explains_install_use_security_and_audio_ducking():
    root_readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    guide = (REPO_ROOT / "docs" / "html_whiteboard.md").read_text(encoding="utf-8")
    template_tools = (APP_DIR / "agent_workspace_template" / "TOOLS.md").read_text(encoding="utf-8")

    assert "docs/html_whiteboard.md" in root_readme
    assert "在白板打開 HTML 互動示範" in root_readme
    assert "Microsoft Edge" in guide
    assert "html_audio_duck_volume" in guide
    assert "show-html" in guide
    assert "reload --content-id" in guide
    assert "安全與資料邊界" in guide
    assert "apps/html_whiteboard_demo/index.html" in template_tools


def test_public_agent_instructions_require_single_file_mobile_ready_games():
    template_agents = (APP_DIR / "agent_workspace_template" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    template_tools = (APP_DIR / "agent_workspace_template" / "TOOLS.md").read_text(
        encoding="utf-8"
    )
    guide = (REPO_ROOT / "docs" / "html_whiteboard.md").read_text(encoding="utf-8")

    assert "製作與修改標準見 `TOOLS.md`" in template_agents
    assert "apps/<name>/index.html" in template_tools
    assert "內嵌 CSS、JS 與小素材" in template_tools
    assert "不依賴 CDN、remote API、install、build、ES module import" in template_tools
    assert "同時支援桌面白板與手機" in template_tools
    assert "純觸控可完成" in template_tools
    assert "桌面與手機相容標準" in guide
    assert "viewport-fit=cover" in guide
