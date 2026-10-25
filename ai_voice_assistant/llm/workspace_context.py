"""Small shared helpers for CLI workspace paths and missing-file bootstrap."""
from pathlib import Path
import shutil


def resolve_project_dir(project_dir, app_dir):
    path = Path(project_dir or "./agent_workspace").expanduser()
    return (path if path.is_absolute() else Path(app_dir) / path).resolve()


def bootstrap_workspace_files(project_dir, template_dir, files, on_copy=None):
    root, template = Path(project_dir).resolve(), Path(template_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in dict.fromkeys(str(f).strip() for f in files if str(f).strip()):
        source, destination = (template / name).resolve(), (root / name).resolve()
        # Templates can only fill project-relative paths, never overwrite an
        # existing private file or follow a configured path outside the roots.
        if not source.is_relative_to(template) or not destination.is_relative_to(root):
            continue
        if destination.exists() or not source.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if on_copy:
            on_copy(source, destination)
