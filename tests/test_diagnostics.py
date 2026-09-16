import os
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from verbose_c.engine.engine import run_bytecode_file, run_source_file
from verbose_c.engine.recorder import PipelineRecorder
from verbose_c.error import (
    DiagnosticEntry, DiagnosticReport, TracebackFrame,
    VBCBytecodeError, VBCCompileError, VBCIOError, VBCRuntimeError,
)
from verbose_c.error.format import format_error, format_report
from verbose_c.fs.artifact_store import ArtifactStore
from verbose_c.fs.source_manager import SourceManager
from verbose_c.parser.lexer.tokenizer import Tokenizer
from verbose_c.parser.ppg.error_collector import ErrorCollector


@pytest.mark.parametrize("source,reason", [
    ("int main() { return ;", "解析"),
    ('int main() { return "错误类型"; }', "类型"),
    ("int main() { return `; }", "非法字符"),
    ("int divide(int n) { return 10 / n; } int main() { return divide(0); }", "除零"),
    ('int main() { return write(STDIN, "失败"); }', "写入失败"),
    ('int main() { read(STDOUT, 1); return 0; }', "读取失败"),
])
def test_failure_channel_and_dump_contract(tmp_path, capsys, source, reason):
    """同一错误只写入 stderr 一次，开启记录后复用完整诊断正文。"""
    path = tmp_path / "diagnostic.vbc"
    path.write_text(source, encoding="utf-8")
    diagnostics = []
    for recording in (False, True):
        dump = tmp_path / "diagnostic.md" if recording else None
        result = run_source_file(
            str(path), log_modules=set(), dump_modules=set(),
            dump_path=str(dump) if dump else None,
            output_path=str(tmp_path / "diagnostic.vbb"),
        )
        captured = capsys.readouterr()
        assert not result.success and result.exit_code == 1
        assert reason in captured.err
        assert "意外的内部错误" not in captured.err
        assert reason not in captured.out
        assert "Traceback (most recent call last)" not in captured.err
        diagnostics.append(captured.err)
        if dump:
            recorded = dump.read_text(encoding="utf-8").split("## 错误信息\n\n```text\n", 1)[1].split("```", 1)[0]
            assert recorded == captured.err
    assert diagnostics[0] == diagnostics[1]


def test_recorder_has_no_error_printing_side_effect(tmp_path, capsys):
    """记录器直接接收错误时也不向终端打印。"""
    recorder = PipelineRecorder(source_filename="example.vbc", dump_path=str(tmp_path / "error.md"))
    recorder.on_error(VBCRuntimeError("测试运行错误", traceback=[]))
    recorder.on_error(VBCCompileError("第二个错误"))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    text = (tmp_path / "error.md").read_text(encoding="utf-8")
    assert text.count("测试运行错误") == 1
    assert "第二个错误" not in text


def test_runtime_error_default_tracebacks_are_independent():
    """默认调用栈为各实例独立的空列表。"""
    first = VBCRuntimeError("第一项")
    second = VBCRuntimeError("第二项")
    assert first.traceback == second.traceback == []
    first.traceback.append(None)
    assert second.traceback == []


@pytest.mark.parametrize("level", [0, 1])
def test_runtime_failure_across_source_cache_and_bytecode(tmp_path, monkeypatch, capsys, level):
    """源码、缓存命中和删除源码后的字节码均保留原因及真实调用位置。"""
    source = tmp_path / "nested.vbc"
    artifact = tmp_path / "nested.vbb"
    source.write_text(
        "int divide(int n) {\n    if (n != 0) { return divide(0); }\n    return 10 / n;\n}\n"
        "int outer(int n) {\n    return divide(n);\n}\n"
        'int main() {\n    int marker = 123;\n    return outer(marker - 123);\n}\n',
        encoding="utf-8",
    )
    options = dict(log_modules=set(), dump_modules=set(), output_path=str(artifact), optimize_level=level)
    result = run_source_file(str(source), **options)
    first = capsys.readouterr()
    assert isinstance(result.error, VBCRuntimeError)
    assert result.exit_code == 1 and first.out == ""
    assert "除零" in first.err and str(source) in first.err
    stack = [frame.scope_name for frame in result.error.traceback]
    assert stack[-3:] == ["main", "outer", "divide"]
    assert result.error.traceback[-1].line == 3
    compile_spy = Mock(side_effect=AssertionError("缓存不应重新编译"))
    monkeypatch.setattr("verbose_c.engine.engine.compile_module", compile_spy)
    result = run_source_file(str(source), **options)
    cached = capsys.readouterr()
    assert not result.success and cached == first
    compile_spy.assert_not_called()
    source.unlink()
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    loaded = capsys.readouterr()
    assert result.exit_code == 1 and loaded.out == first.out
    assert str(source) in loaded.err and "第 3 行" in loaded.err
    assert "除零" in loaded.err and "return 10 / n" not in loaded.err
    assert "Traceback (most recent call last)" not in loaded.err


def test_formatter_tree_and_chinese_tab_alignment(capsys):
    """固定树形布局，并检查中文和制表符后的指示线位置。"""
    report = DiagnosticReport("解析错误", [DiagnosticEntry(
        "缺少表达式", filepath="例子.vbc", line=1, column=6,
        source_context=[(1, "\t中文 + ;")], rule_stack=["start", "expect"],
    )])
    assert format_report(report) == "\n".join([
        " ├─ 错误位置: 文件 例子.vbc，第 1 行，第 7 列",
        " ├─ 解析错误: 缺少表达式",
        " ├─ 错误上下文:",
        " │  1 |     中文 + ;",
        " │  " + " " * 15 + "^",
        " └─ 语法解析规则调用栈:",
        "    start -> expect",
    ])
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [
    VBCCompileError("缺少信息"), VBCRuntimeError("缺少信息"),
    VBCIOError("缺少信息"), VBCBytecodeError("缺少信息"),
    VBCRuntimeError("缺少信息", [TracebackFrame("", -1, "unknown")]),
])
def test_formatter_accepts_missing_metadata(error, capsys):
    """位置和上下文缺省时保持原因完整，不输出伪造位置。"""
    diagnostic = format_error(error)
    assert diagnostic.count("缺少信息") == 1
    assert all(text not in diagnostic for text in ("文件 None", "第 0 行", "第 -1 行", "第 None"))
    assert capsys.readouterr() == ("", "")


def test_exception_compatibility_and_broken_report_fallback():
    """旧异常调用签名保持兼容，报告损坏也不丢失最初的错误。"""
    warnings = ["已有告警"]
    error = VBCCompileError("原始原因", 7, "sample.vbc", warnings)
    assert (str(error), error.message, error.line, error.filepath, error.warnings) == (
        "原始原因", "原始原因", 7, "sample.vbc", warnings,
    )
    error.report = object()
    assert format_error(error) == "编译错误: 文件 sample.vbc\n原始原因"


def test_parse_error_points_to_included_file(tmp_path, capsys):
    """复用 include 解析错误样例，定位真实文件并保留规则栈。"""
    fixtures = Path(__file__).parent / "error"
    for name in ("report_test.vbc", "report_bad.inc"):
        (tmp_path / name).write_text((fixtures / name).read_text(encoding="utf-8"), encoding="utf-8")
    result = run_source_file(str(tmp_path / "report_test.vbc"), log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    entry = result.error.report.entries[0]
    assert entry.filepath == str(tmp_path / "report_bad.inc")
    assert entry.line == 5 and entry.column == 4
    assert entry.actual_token == "int" and entry.expected_tokens
    assert entry.rule_stack[0] == "start"
    assert "int broken = ;" in captured.err and "语法解析规则调用栈" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("ending,line,column", [("", 2, 10), ("\n", 3, 0)])
def test_eof_diagnostic_and_legacy_parser_report(tmp_path, capsys, ending, line, column):
    """EOF 使用末尾位置和至少一个指示字符，旧字符串接口复用格式化器。"""
    source = tmp_path / "eof.vbc"
    source.write_text("int main() {\n\treturn 1;" + ending, encoding="utf-8")
    result = run_source_file(str(source), log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    entry = result.error.report.entries[0]
    assert entry.actual_token == "EOF" and entry.line == line and entry.column == column
    assert "^" in captured.err and "EOF" in captured.err
    tokenizer = Tokenizer(str(source), SourceManager())
    collector = ErrorCollector(tokenizer)
    assert collector.format_error_report() == "没有发现解析错误"
    tokenizer._index = len(tokenizer.tokens) - 1
    collector.record_expectation(tokenizer._index, "}")
    collector.add_error(tokenizer._index, "缺少右括号")
    assert collector.format_error_report() == format_report(collector.get_report())


@pytest.mark.parametrize("included", [False, True])
def test_lexical_error_has_real_source_location(tmp_path, capsys, included):
    """入口和 include 的词法错误均作为编译错误展示真实行列。"""
    entry = tmp_path / "entry.vbc"
    invalid = tmp_path / "invalid.inc" if included else entry
    invalid.write_text("// 注释\nint x = `;\n", encoding="utf-8")
    if included:
        entry.write_text('#include "invalid.inc"\n', encoding="utf-8")
    result = run_source_file(str(entry), log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    assert isinstance(result.error, VBCCompileError)
    diagnostic = result.error.report.entries[0]
    assert (diagnostic.filepath, diagnostic.line, diagnostic.column) == (str(invalid), 2, 8)
    assert "词法错误" in captured.err and "第 2 行，第 9 列" in captured.err
    assert captured.out == "" and "Traceback" not in captured.err


def test_type_errors_preserve_order_and_positions(tmp_path, capsys):
    """返回值与参数错误各自保留位置和原始顺序。"""
    path = tmp_path / "types.vbc"
    path.write_text(
        'int broken() { return "wrong"; }\n'
        'int identity(int n) { return n; }\n'
        'int main() { return identity("wrong"); }\n', encoding="utf-8",
    )
    result = run_source_file(str(path), log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    entries = result.error.report.entries
    assert len(entries) == 2
    assert [entry.line for entry in entries] == [1, 3]
    assert "应返回" in entries[0].message and "函数参数 1" in entries[1].message
    assert captured.err.index("应返回") < captured.err.index("函数参数 1")
    assert captured.err.count(" ├─ ") == captured.err.count(" └─ ") == 1
    assert captured.out == ""


@pytest.mark.parametrize("kind", ["missing", "truncated", "version"])
def test_bytecode_load_diagnostic_uses_artifact_path(tmp_path, capsys, kind):
    """缺失、截断和版本不兼容的字节码均定位产物文件。"""
    path = tmp_path / "invalid.vbb"
    if kind != "missing":
        ArtifactStore().save_bytecode(str(path), [], metadata={})
        data = bytearray(path.read_bytes())
        if kind == "truncated":
            data = data[:12]
        else:
            struct.pack_into("<H", data, 4, 65535)
        path.write_bytes(data)
    result = run_bytecode_file(str(path), log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    assert isinstance(result.error, VBCBytecodeError) and result.exit_code == 1
    assert result.error.filepath == str(path)
    assert str(path) in captured.err and "字节码错误" in captured.err
    assert "Traceback" not in captured.err and captured.out == ""
    if kind == "version":
        assert "版本" in captured.err


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("body,reason", [
    ("int fail(int n) { return 10 / n; }", "除零错误"),
    ("int fail(int n) { return 2147483647 + n + 1; }", "整数溢出"),
    ("int fail(int n) { return (char)(n + 300); }", "数值转换失败"),
    ("int fail(int n) { return write(STDIN, \"失败\"); }", "写入失败"),
    ("int fail(int n) { read(STDOUT, 1); return 0; }", "读取失败"),
])
def test_runtime_diagnostics_across_cli_backends(tmp_path, level, body, reason):
    """对照 O0/O1 下源码、缓存、字节码、内存执行和独立 exe 的输出契约。"""
    source = tmp_path / "runtime.vbc"
    artifact = tmp_path / "runtime.vbb"
    executable = tmp_path / "runtime.exe"
    source.write_text(body + '\nint main() { write(STDOUT, "开始"); return fail(0); }', encoding="utf-8")
    prefix = [sys.executable, "-m", "verbose_c.cli"]
    environment = {**os.environ, "PYTHONUTF8": "1"}
    source_command = prefix + [str(source), f"-O{level}", "-o", str(artifact)]
    commands = [source_command, source_command, prefix + [str(artifact)]]
    if sys.platform == "win32":
        compiled = subprocess.run(
            source_command + ["--emit-exe", str(executable)],
            input=b"", capture_output=True, timeout=30, env=environment,
        )
        assert compiled.returncode == 0, compiled.stderr.decode("utf-8")
        assert compiled.stderr == b""
        commands += [
            source_command + ["--run-native-memory"],
            prefix + [str(artifact), "--run-native-memory"], [str(executable)],
        ]
        # 独立输出产物之外，再使用空缓存检验首次源码执行。
        source_command[-1] = str(tmp_path / "fresh.vbb")
    for command in commands:
        completed = subprocess.run(command, input=b"", capture_output=True, timeout=30, env=environment)
        diagnostic = completed.stderr.decode("utf-8")
        assert completed.returncode == 1, (command, completed.stdout, diagnostic)
        assert completed.stdout.decode("utf-8") == "开始", (command, diagnostic)
        assert reason in diagnostic and "Traceback" not in diagnostic


@pytest.mark.parametrize("no_warn", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_cli_warning_switch_does_not_hide_errors(tmp_path, no_warn, failure):
    """警告开关只影响既有警告输出，错误和正常返回码保持独立。"""
    path = tmp_path / "warnings.vbc"
    ending = 'return "wrong";' if failure else "return value;"
    path.write_text(f"int main() {{ int value = 1.5; {ending} }}", encoding="utf-8")
    command = [sys.executable, "-m", "verbose_c.cli", str(path)]
    if no_warn:
        command.append("--no-warn")
    completed = subprocess.run(command, input=b"", capture_output=True, timeout=30,
                               env={**os.environ, "PYTHONUTF8": "1"})
    assert completed.returncode == 1
    assert ("警告:" in completed.stdout.decode("utf-8")) == (not no_warn)
    if failure:
        assert "应返回" in completed.stderr.decode("utf-8")
    else:
        assert completed.stderr == b""


@pytest.mark.skipif(sys.platform != "win32", reason="内存执行需要 Windows x64")
@pytest.mark.parametrize("level", [0, 1])
def test_native_runtime_error_uses_deleted_embedded_source(tmp_path, capsys, level):
    """Native 字节码执行失败仍定位内嵌源码，保持运行时错误分类。"""
    source = tmp_path / "deleted.vbc"
    artifact = tmp_path / "deleted.vbb"
    source.write_text("int fail(int n) { return 10 / n; } int main() { return fail(0); }", encoding="utf-8")
    prepared = run_source_file(
        str(source), log_modules=set(), dump_modules=set(), execute=False,
        output_path=str(artifact), optimize_level=level,
    )
    assert prepared.success
    source.unlink()
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set(), run_native_memory=True)
    captured = capsys.readouterr()
    assert isinstance(result.error, VBCRuntimeError) and result.exit_code == 1
    assert result.error.filepath == str(source)
    assert result.error.report.entries[0].line == 1
    assert "除零" in captured.err and str(source) in captured.err
    assert "编译错误" not in captured.err and captured.out == ""


@pytest.mark.parametrize("code", ["return 23;", "exit(23);"])
def test_normal_nonzero_exit_is_successful(tmp_path, capsys, code):
    """正常 return 和 exit 的非零返回值不会被转成诊断失败。"""
    source = tmp_path / "exit.vbc"
    source.write_text(f"int main() {{ {code} }}", encoding="utf-8")
    result = run_source_file(str(source), log_modules=set(), dump_modules=set())
    assert result.success and result.exit_code == 23 and result.error is None
    assert capsys.readouterr() == ("", "")


def test_unreadable_source_context_does_not_replace_runtime_error(tmp_path, capsys):
    """源码编码损坏时，字节码错误原因与位置仍可用于诊断。"""
    source = tmp_path / "unreadable.vbc"
    artifact = tmp_path / "unreadable.vbb"
    source.write_text("int fail(int n) { return 10 / n; } int main() { return fail(0); }", encoding="utf-8")
    assert run_source_file(
        str(source), log_modules=set(), dump_modules=set(), execute=False, output_path=str(artifact),
    ).success
    source.write_bytes(b"\xff\xfe\xff")
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    assert isinstance(result.error, VBCRuntimeError)
    assert "除零" in captured.err and str(source) in captured.err
    assert "UnicodeDecodeError" not in captured.err and captured.out == ""


@pytest.mark.parametrize("extension", ["vbc", "vbb"])
@pytest.mark.parametrize("recording", [False, True])
def test_cli_missing_input_uses_pipeline_diagnostics(tmp_path, monkeypatch, capsys, extension, recording):
    """CLI 缺失输入也经过统一流水线，保留 stderr 和 dump 的相同正文。"""
    from verbose_c.cli import main

    source = tmp_path / f"missing.{extension}"
    dump = tmp_path / "missing.md"
    arguments = ["verbose-c", str(source)] + (["--dump", "vm"] if recording else [])
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr("verbose_c.cli.create_dump_path", Mock(return_value=str(dump)))
    with pytest.raises(SystemExit) as raised:
        main()
    captured = capsys.readouterr()
    assert raised.value.code == 1
    assert str(source) in captured.err and "无法读取" in captured.err
    assert "Traceback" not in captured.err and "无法读取" not in captured.out
    if recording:
        assert captured.err in dump.read_text(encoding="utf-8")
    else:
        assert captured.out == "" and not dump.exists()
