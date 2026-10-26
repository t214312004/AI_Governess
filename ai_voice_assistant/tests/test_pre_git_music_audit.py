"""The staged-file gate also catches music exported outside the default library."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('name',['exported-song.mp3','custom-library/catalog.sqlite3'])
def test_audit_blocks_staged_media_outside_ignored_default(tmp_path,name):
    shell=shutil.which('powershell')
    if not shell:pytest.skip('PowerShell audit gate')
    repository=Path(__file__).resolve().parents[2]
    (tmp_path/'scripts').mkdir()
    shutil.copyfile(repository/'scripts/pre_git_audit.ps1',tmp_path/'scripts/pre_git_audit.ps1')
    (tmp_path/'.gitignore').write_text('# test repository\n')
    def run(argv):
        return subprocess.run(argv,cwd=tmp_path,capture_output=True,text=True,timeout=20,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert run(['git','init','-q']).returncode==0
    audit=[shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(tmp_path/'scripts/pre_git_audit.ps1')]
    assert run(audit).returncode==0
    target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'private-test-data')
    assert run(['git','add','--',name]).returncode==0
    rejected=run(audit)
    assert rejected.returncode==1 and '[ERROR]' in rejected.stdout
