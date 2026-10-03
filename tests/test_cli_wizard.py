import argparse

from sparky import cli, config, hardware, runtime
from sparky.ollama import PullProgress
from sparky.wizard import Wizard, copy_app


def test_options_before_a_subcommand_are_kept():
    args = cli.build_parser().parse_args(["--mode", "code", "--model", "x", "web", "--no-browser"])
    assert args.command == "web" and args.mode == "code" and args.model == "x" and args.no_browser
    args = cli.build_parser().parse_args(["web", "--mode", "study"])
    assert args.mode == "study"
    args = cli.build_parser().parse_args(["ask", "why", "is", "the", "sky", "blue"])
    assert args.prompt == ["why", "is", "the", "sky", "blue"]


def test_target_specs():
    assert cli._targets("this") == [hardware.target()]
    assert cli._targets("all") == runtime.DEFAULT_TARGETS
    assert cli._targets("macos,windows") == ["macos-aarch64", "macos-x86_64", "windows-x86_64"]
    assert cli._targets("linux-aarch64") == ["linux-aarch64"]


def test_pull_progress_sums_layers():
    p = PullProgress()
    assert p.update({"status": "pulling manifest"}) == "pulling manifest"
    p.update({"status": "pulling abc", "digest": "a", "total": 1000, "completed": 250})
    line = p.update({"status": "pulling def", "digest": "b", "total": 1000, "completed": 750})
    assert line.startswith("downloading") and " 50%" in line
    assert p.update({"status": "success"}) == "success"


def test_ollama_client_pull_and_errors(fake_ollama):
    from sparky.ollama import OllamaClient, OllamaError
    c = OllamaClient(fake_ollama.url)
    fake_ollama.pull_events = [{"status": "pulling manifest"}, {"status": "success"}]
    seen = []
    c.pull("x:1b", seen.append)
    assert [e["status"] for e in seen] == ["pulling manifest", "success"]
    fake_ollama.pull_events = [{"status": "pulling manifest"}, {"error": "file does not exist"}]
    try:
        c.pull("nope:1b")
        raise AssertionError("expected OllamaError")
    except OllamaError as e:
        assert "does not exist" in str(e)
    assert c.version() == "0.35.1"
    c.delete("gemma3:1b")
    assert "gemma3:1b" not in [m["name"] for m in c.models()]


def test_copy_app_copies_the_app_but_not_runtime_or_data(tmp_path):
    src = config.find_root()
    dst = tmp_path / "stick"
    dst.mkdir()
    copy_app(src, dst)
    assert (dst / "sparky" / "cli.py").exists()
    assert (dst / "sparky" / "web" / "server.py").exists()
    assert (dst / "sparky.cmd").exists() and (dst / "START.bat").exists()
    assert (dst / "tools" / "fetch_python.sh").exists()
    assert not (dst / "runtime").exists() and not (dst / "data").exists()
    assert not list(dst.rglob("__pycache__"))


def test_wizard_non_interactive_install(tmp_path, monkeypatch):
    stick = tmp_path / "stick"
    calls = {}
    monkeypatch.setattr(runtime, "ensure", lambda root, targets, progress=None, gpu=False:
                        calls.setdefault("targets", targets))
    args = argparse.Namespace(target=str(stick), purposes="code", models=None, ram=16.0,
                              targets="windows,linux", no_models=True, gpu=False, yes=True, force=False)
    cfg = config.load(root=tmp_path)
    assert Wizard(cfg, args).run() == 0
    assert calls["targets"] == ["windows-x86_64", "linux-x86_64"]
    assert (stick / "sparky.cmd").exists() and (stick / "context" / "README.txt").exists()
    written = config.load(root=stick)
    assert written.mode == "code"


def test_wizard_recommends_within_space(tmp_path):
    args = argparse.Namespace(yes=True, models=None)
    w = Wizard(config.load(root=tmp_path), args)
    chosen = w.choose_models(["everyday"], ram=8, space=10)
    assert chosen and chosen[0] == "qwen3.5:4b"


def test_wizard_refuses_fat32(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hardware, "fstype", lambda p: "vfat")
    args = argparse.Namespace(force=False, yes=True)
    assert Wizard(config.load(root=tmp_path), args).check_drive(tmp_path) is False
    assert "exFAT" in capsys.readouterr().out


def test_hardware_probes_do_not_crash(tmp_path):
    assert hardware.total_ram_gb() >= 0
    assert hardware.free_gb(tmp_path) > 0
    assert isinstance(hardware.list_drives(), list)
    assert hardware.fs_problem("vfat") and hardware.fs_problem("exfat") is None
    assert hardware.fs_warning("ntfs") and hardware.fs_warning("exfat") is None
    assert hardware._normalise_fs("msdos") == "vfat" and hardware._normalise_fs("fuseblk") == "ntfs"
    assert hardware.target().count("-") == 1
