from pathlib import Path

from sparky import tools


def test_write_then_read(tmp_path):
    out = tools.run_tool("write_file", {"path": "a.txt", "content": "hello"}, cwd=tmp_path)
    assert "Wrote" in out
    body = tools.run_tool("read_file", {"path": "a.txt"}, cwd=tmp_path)
    assert body == "hello"


def test_edit_file_unique(tmp_path):
    (tmp_path / "f.py").write_text("x = 1\ny = 2\n")
    out = tools.run_tool("edit_file", {"path": "f.py", "old_str": "x = 1", "new_str": "x = 99"}, cwd=tmp_path)
    assert "Edited" in out
    assert "x = 99" in (tmp_path / "f.py").read_text()


def test_edit_file_ambiguous(tmp_path):
    (tmp_path / "f.py").write_text("a\na\n")
    out = tools.run_tool("edit_file", {"path": "f.py", "old_str": "a", "new_str": "b"}, cwd=tmp_path)
    assert "appears 2 times" in out


def test_list_dir(tmp_path):
    (tmp_path / "one.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    out = tools.run_tool("list_dir", {}, cwd=tmp_path)
    assert "one.txt" in out
    assert "d sub" in out


def test_search(tmp_path):
    (tmp_path / "code.py").write_text("def foo():\n    return 42\n")
    out = tools.run_tool("search", {"pattern": r"def \w+"}, cwd=tmp_path)
    assert "code.py:1" in out and "def foo" in out


def test_run_shell_confirm_denied(tmp_path):
    out = tools.run_tool("run_shell", {"command": "echo hi"}, cwd=tmp_path, confirm=lambda c: False)
    assert "not approved" in out


def test_run_shell_confirm_allowed(tmp_path):
    out = tools.run_tool("run_shell", {"command": "echo hi"}, cwd=tmp_path, confirm=lambda c: True)
    assert "hi" in out and "exit 0" in out
