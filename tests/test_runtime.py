import hashlib
import io
import os
import tarfile
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sparky import runtime


class RangeHandler(SimpleHTTPRequestHandler):
    """Static files with HTTP Range support, like GitHub's asset CDN."""

    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        data = open(path, "rb").read()
        start, end = rng.split("=")[1].split("-")
        start, end = int(start), int(end or len(data) - 1)
        chunk = data[start:end + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        return io.BytesIO(chunk)


@pytest.fixture
def files(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(RangeHandler, directory=str(root)))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield root, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    d = tmp_path / "cache"
    d.mkdir()
    monkeypatch.setattr(runtime, "cache_dir", lambda: d)
    runtime._SUMS.clear()


def test_gpu_and_unsafe_members_are_recognised():
    assert runtime._is_gpu("lib/ollama/cuda_v12/libggml-cuda.so")
    assert runtime._is_gpu("lib/ollama/vulkan/libggml-vulkan.so")
    assert runtime._is_gpu("lib/ollama/ggml-cuda.dll")
    assert not runtime._is_gpu("lib/ollama/libggml-cpu-haswell.so")
    assert not runtime._is_gpu("lib/ollama/MLX_LICENSE")
    assert not runtime._is_gpu("ollama.exe")
    assert not runtime._safe_member("../evil")
    assert not runtime._safe_member("/etc/passwd")
    assert not runtime._safe_member("C:/x")
    assert runtime._safe_member("lib/ollama/x.so")


def test_range_file_reads_only_the_needed_members(files, tmp_path):
    root, url = files
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ollama.exe", b"MZ" + b"x" * 1000)
        z.writestr("lib/ollama/ggml-cpu-x64.dll", b"cpu" * 100)
        z.writestr("lib/ollama/cuda_v12/ggml-cuda.dll", os.urandom(3_000_000))
    (root / "o.zip").write_bytes(buf.getvalue())
    src = runtime.RangeFile(f"{url}/o.zip")
    out = tmp_path / "out"
    runtime._extract_zip(zipfile.ZipFile(src), out, runtime._is_gpu)
    assert (out / "ollama.exe").read_bytes().startswith(b"MZ")
    assert (out / "lib/ollama/ggml-cpu-x64.dll").exists()
    assert not (out / "lib/ollama/cuda_v12").exists()
    assert len(src.blocks) < 3        # the 3 MB GPU file was never fetched


def test_verified_download_checks_the_published_sum(files):
    root, url = files
    (root / "a.tgz").write_bytes(b"payload")
    good = hashlib.sha256(b"payload").hexdigest()
    (root / "SUMS").write_text(f"{good}  ./a.tgz\n{'0' * 64}  b.tgz\n")
    path = runtime.verified_download(url, "SUMS", "a.tgz", None)
    assert path.read_bytes() == b"payload"
    (root / "b.tgz").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        runtime.verified_download(url, "SUMS", "b.tgz", None)
    with pytest.raises(RuntimeError, match="not in the release checksum list"):
        runtime.verified_download(url, "SUMS", "c.tgz", None)


def test_ensure_python_unpacks_prunes_and_stamps(files, tmp_path, monkeypatch):
    root, url = files
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("python/bin/python3.12", b"#!bin"), ("python/lib/python3.12/os.py", b"x"),
                           ("python/lib/python3.12/test/big.py", b"y"), ("python/include/h.h", b"z")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("python/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3.12"
        tar.addfile(link)
    triple = runtime.TARGETS["linux-x86_64"][0]
    asset = f"cpython-{runtime.PBS_PY}+{runtime.PBS_TAG}-{triple}-install_only_stripped.tar.gz"
    (root / asset).write_bytes(buf.getvalue())
    (root / "SHA256SUMS").write_text(f"{hashlib.sha256(buf.getvalue()).hexdigest()}  {asset}\n")
    monkeypatch.setattr(runtime, "PBS_URL", url)
    stick = tmp_path / "stick"
    exe = runtime.ensure_python(stick, "linux-x86_64")
    d = runtime.python_dir(stick, "linux-x86_64")
    assert exe == d / "bin" / "python3.12"
    assert (d / "lib/python3.12/os.py").exists()
    assert not (d / "lib/python3.12/test").exists() and not (d / "include").exists()
    assert not (d / "bin" / "python3").exists()          # links dropped, not tripled
    assert runtime.current(d, runtime.PBS_PY)
    assert runtime.ensure_python(stick, "linux-x86_64") == exe   # second call is a no-op


def test_layout_helpers(tmp_path):
    assert runtime.ollama_dir(tmp_path, "macos-x86_64") == runtime.ollama_dir(tmp_path, "macos-aarch64")
    d = runtime.ollama_dir(tmp_path, "windows-x86_64")
    d.mkdir(parents=True)
    (d / "ollama.exe").write_bytes(b"MZ")
    p = runtime.python_dir(tmp_path, "windows-x86_64")
    p.mkdir(parents=True)
    (p / "python.exe").write_bytes(b"MZ")
    assert runtime.installed_targets(tmp_path) == ["windows-x86_64"]
    assert set(runtime.DEFAULT_TARGETS) <= set(runtime.TARGETS)


def test_server_env_keeps_state_on_the_stick(tmp_path):
    env = runtime.server_env(tmp_path, "http://127.0.0.1:11555")
    assert env["OLLAMA_MODELS"] == str(tmp_path / "runtime" / "ollama" / "models")
    assert env["OLLAMA_HOST"] == "127.0.0.1:11555"
    assert env["HOME"] == str(tmp_path / "data" / "home")
