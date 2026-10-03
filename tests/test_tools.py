from sparky import tools


def test_write_read_edit_inside_the_working_folder(tmp_path):
    asked = []
    confirm = lambda what: asked.append(what) or False  # noqa: E731
    assert "Wrote" in tools.run_tool("write_file", {"path": "a.txt", "content": "hello world"},
                                     cwd=tmp_path, confirm=confirm)
    assert tools.run_tool("read_file", {"path": "a.txt"}, cwd=tmp_path) == "hello world"
    assert "Edited" in tools.run_tool("edit_file", {"path": "a.txt", "old_str": "world", "new_str": "there"},
                                      cwd=tmp_path, confirm=confirm)
    assert (tmp_path / "a.txt").read_text() == "hello there"
    assert asked == []      # nothing inside the folder needs approval


def test_writes_outside_the_working_folder_ask_first(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "elsewhere.txt"
    asked = []
    out = tools.run_tool("write_file", {"path": str(outside), "content": "x"}, cwd=work,
                         confirm=lambda what: asked.append(what) or False)
    assert "did not allow" in out and not outside.exists()
    assert asked and "outside the working folder" in asked[0]
    out = tools.run_tool("write_file", {"path": "../elsewhere.txt", "content": "y"}, cwd=work,
                         confirm=lambda what: True)
    assert outside.read_text() == "y"


def test_edit_needs_a_unique_match(tmp_path):
    (tmp_path / "f.py").write_text("a = 1\na = 1\n")
    out = tools.run_tool("edit_file", {"path": "f.py", "old_str": "a = 1", "new_str": "b"}, cwd=tmp_path)
    assert "2 times" in out
    out = tools.run_tool("edit_file", {"path": "f.py", "old_str": "zzz", "new_str": "b"}, cwd=tmp_path)
    assert "not found" in out


def test_list_and_search(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.py").write_text("def hello():\n    pass\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.py").write_text("def hello(): pass\n")
    assert "d sub" in tools.run_tool("list_dir", {}, cwd=tmp_path)
    found = tools.run_tool("search", {"pattern": "def hello"}, cwd=tmp_path)
    assert "x.py:1" in found and "node_modules" not in found
    assert "bad regex" in tools.run_tool("search", {"pattern": "("}, cwd=tmp_path)


def test_shell_asks_and_reports_exit_code(tmp_path):
    asked = []
    out = tools.run_tool("run_shell", {"command": "echo hi"}, cwd=tmp_path,
                         confirm=lambda what: asked.append(what) or True)
    assert asked == ["run: echo hi"]
    assert "(exit 0)" in out and "hi" in out
    out = tools.run_tool("run_shell", {"command": "echo hi"}, cwd=tmp_path, confirm=lambda what: False)
    assert "did not approve" in out


def test_unknown_tool_and_missing_file(tmp_path):
    assert "unknown tool" in tools.run_tool("fly", {}, cwd=tmp_path)
    assert "not found" in tools.run_tool("read_file", {"path": "nope.txt"}, cwd=tmp_path)


def test_read_falls_back_to_the_working_folder_for_invented_paths(tmp_path):
    (tmp_path / "notes.txt").write_text("found it")
    assert tools.run_tool("read_file", {"path": "/notes.txt"}, cwd=tmp_path) == "found it"
    assert "not found" in tools.run_tool("read_file", {"path": "/nope/missing.txt"}, cwd=tmp_path)
