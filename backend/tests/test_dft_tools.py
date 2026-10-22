"""Installer logic without the network: fake Materials Cloud listing and downloads; implicit local targets."""

import hashlib
import io
import json
import tarfile

import pytest

from app.config import get_settings
from app.dft import execute, tools
from app.dft.codes import REGISTRY


@pytest.fixture
def tools_home(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "TOOLS_DIR", tmp_path / "tools")
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", None)
    return tmp_path / "tools"


def fake_sssp(n_elements: int = 60):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for i in range(n_elements):
            data = f'<UPF><PP_HEADER element="X{i}" functional="PBE" wfc_cutoff="30" rho_cutoff="240"/></UPF>'.encode()
            info = tarfile.TarInfo(f"SSSP_1.3.0_PBE_efficiency/X{i}.pbe.UPF")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    table = {f"X{i}": {"filename": f"X{i}.pbe.UPF", "cutoff_wfc": 30.0, "cutoff_rho": 240.0} for i in range(n_elements)}
    return buf.getvalue(), json.dumps(table).encode()


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def patch_mc(monkeypatch, tar_bytes, json_bytes, corrupt=False):
    files = {"SSSP_1.3.0_PBE_efficiency.tar.gz": tar_bytes, "SSSP_1.3.0_PBE_efficiency.json": json_bytes}
    entries = [{"key": k, "checksum": "md5:" + hashlib.md5(v).hexdigest()} for k, v in files.items()]

    def fake_get(url, **kw):
        if url.endswith("/versions/latest"):
            return Resp({"id": "rec-latest"})
        if url.endswith("/files"):
            return Resp({"entries": entries})
        raise AssertionError(url)

    def fake_download(url, dest, log):
        key = url.split("/files/")[1].removesuffix("/content")
        dest.write_bytes(files[key] + (b"x" if corrupt and key.endswith(".tar.gz") else b""))
        return dest

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    monkeypatch.setattr(tools, "_download", fake_download)


def test_sssp_install_verifies_and_enables_espresso(tools_home, monkeypatch):
    tar_bytes, json_bytes = fake_sssp()
    patch_mc(monkeypatch, tar_bytes, json_bytes)
    assert not REGISTRY["espresso"].availability(get_settings())[0]
    tools.install("sssp-pbe", wait=True)
    st = tools._state()["sssp-pbe"]
    assert st["status"] == "installed" and "60 elements" in st["version"], st
    d = tools.managed_pseudo_dir("PBE")
    assert (d / "X0.pbe.UPF").is_file() and (d / "SSSP_1.3.0_PBE_efficiency.json").is_file()
    ok, reason = REGISTRY["espresso"].availability(get_settings())
    assert ok and "SSSP" in reason
    assert tools.managed_pseudo_dir("PBEsol") is None


def test_sssp_install_rejects_bad_checksum(tools_home, monkeypatch):
    tar_bytes, json_bytes = fake_sssp()
    patch_mc(monkeypatch, tar_bytes, json_bytes, corrupt=True)
    tools.install("sssp-pbe", wait=True)
    st = tools._state()["sssp-pbe"]
    assert st["status"] == "failed" and "MD5 mismatch" in st["message"]
    assert tools.managed_pseudo_dir("PBE") is None


def test_vasp_cannot_be_installed(tools_home):
    with pytest.raises(tools.ToolError, match="commercial"):
        tools.install("vasp")


def test_installed_code_gets_an_implicit_local_target(tools_home, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "COMPUTE_CONFIG", tmp_path / "none.yaml")
    exe = tools_home / "envs" / "qe" / "bin" / "pw.x"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    tools._set("qe", status="installed", version="7.6")
    targets = execute.load_targets()
    assert targets["local"]["codes"]["espresso"]["executable"] == str(exe)
    assert "espresso" in next(t for t in execute.describe_targets() if t["name"] == "local")["codes"]


def _dead_pid() -> int:
    import subprocess
    import sys

    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_interrupted_installs_are_settled_from_disk(tools_home):
    # qe finished on disk before its process died; abinit did not; sssp-pbe's process is still alive (this one)
    exe = tools_home / "envs" / "qe" / "bin" / "pw.x"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    (tools_home / "envs" / "qe" / "conda-meta").mkdir()
    (tools_home / "envs" / "qe" / "conda-meta" / "qe-7.6-x.json").write_text(json.dumps({"name": "qe", "version": "7.6"}))
    dead = _dead_pid()
    tools._set("qe", status="installing", pid=dead)
    tools._set("abinit", status="installing", pid=None)
    tools._set("sssp-pbe", status="installing", pid=__import__("os").getpid())
    assert sorted(tools.recover_interrupted()) == ["abinit", "qe"]
    st = tools._state()
    assert st["qe"]["status"] == "installed" and st["qe"]["version"] == "7.6"
    assert st["abinit"]["status"] == "failed" and "Retry" in st["abinit"]["message"]
    assert st["sssp-pbe"]["status"] == "installing"


def test_a_dead_install_does_not_block_a_retry(tools_home, monkeypatch):
    started, dead = [], _dead_pid()

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append(cmd)
            self.pid = 4242

    monkeypatch.setattr(tools.subprocess, "Popen", FakePopen)
    tools._set("gpaw", status="installing", pid=dead)
    st = tools.install("gpaw")
    assert st["status"] == "installing" and st["pid"] == 4242
    assert started[0][-3:] == ["-m", "app.dft.tools", "gpaw"]
    monkeypatch.setattr(tools, "_alive", lambda pid: True)
    with pytest.raises(tools.ToolError, match="already being installed"):
        tools.install("gpaw")


def test_maud_macos_bundle_layout(tools_home, monkeypatch):
    from app.xrd import engines

    monkeypatch.setattr(tools.platform, "system", lambda: "Darwin")
    contents = tools_home / "apps" / "maud" / "Maud.app" / "Contents"
    java = contents / "PlugIns" / "Home" / "bin" / "java"
    java.parent.mkdir(parents=True)
    java.write_text("")
    (contents / "Java").mkdir()
    (contents / "Java" / "Maud.jar").write_text("")
    tools._set("maud", status="installed")
    assert tools.managed_executable("maud") == java
    assert engines._maud_paths() == (java, contents / "Java")
