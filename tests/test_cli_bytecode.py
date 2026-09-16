import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("optimization_level", [0, 1])
@pytest.mark.parametrize("explicit_output", [False, True])
def test_cli_bytecode_roundtrip_without_source(tmp_path, optimization_level, explicit_output):
    """验证默认缓存或指定路径的字节码在源码移除后仍独立运行。"""
    source = tmp_path / "program.vbc"
    source.write_text('int main() { write(STDOUT, "字节码"); return 23; }', encoding="utf-8")
    artifact = tmp_path / "explicit.vbb" if explicit_output else tmp_path / "__vbccache__" / "program.vbb"
    command = [sys.executable, "-m", "verbose_c.cli", str(source), "--compile-only", f"-O{optimization_level}"]
    if explicit_output:
        command += ["-o", str(artifact)]
    env = {**os.environ, "PYTHONUTF8": "1"}
    compiled = subprocess.run(command, capture_output=True, timeout=20, env=env)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    assert compiled.stdout == b""
    assert artifact.is_file()
    source.unlink()
    loaded = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(artifact)],
                            capture_output=True, timeout=20, env=env)
    assert loaded.returncode == 23, loaded.stdout + loaded.stderr
    assert loaded.stdout == "字节码".encode("utf-8")
    assert loaded.stderr == b""


def test_cli_rejects_corrupted_bytecode(tmp_path):
    """损坏字节码应失败，不能打印成功或进入 VM。"""
    artifact = tmp_path / "broken.vbb"
    artifact.write_bytes(b"VBB\0")
    loaded = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(artifact)],
                            capture_output=True, timeout=20, env={**os.environ, "PYTHONUTF8": "1"})
    assert loaded.returncode == 1
    assert "截断" in loaded.stdout.decode("utf-8")
    assert str(artifact) in loaded.stdout.decode("utf-8")


@pytest.mark.parametrize("success,status", [(True, 0), (False, 1)])
def test_cli_parser_generation_propagates_failure(monkeypatch, success, status):
    """解析器生成失败必须使 CLI 和自动验收返回非零退出码。"""
    from verbose_c.cli import main

    monkeypatch.setattr(sys, "argv", ["verbose-c", "Grammar/verbose_c.gram", "--compile-parser"])
    monkeypatch.setattr("verbose_c.cli.run_parser_generation", Mock(return_value=SimpleNamespace(success=success)))
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == status
