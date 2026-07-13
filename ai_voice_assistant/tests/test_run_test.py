from types import SimpleNamespace

import run_test


def test_run_test_uses_current_interpreter_and_propagates_exit_code(mocker, tmp_path):
    output_path = tmp_path / "pytest_clean_output.txt"
    mocker.patch.object(run_test, "OUTPUT_PATH", output_path)
    subprocess_run = mocker.patch(
        "run_test.subprocess.run",
        return_value=SimpleNamespace(returncode=7, stdout="test output", stderr="test error"),
    )

    assert run_test.main() == 7

    args, kwargs = subprocess_run.call_args
    assert args[0][0] == run_test.sys.executable
    assert kwargs["cwd"] == run_test.APP_DIR
    assert kwargs["text"] is True
    assert output_path.read_text(encoding="utf-8") == (
        "STDOUT:\ntest output\nSTDERR:\ntest error"
    )
