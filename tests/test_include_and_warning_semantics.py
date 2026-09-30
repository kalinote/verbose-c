import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from verbose_c.engine.engine import compile_module, run_source_file
from verbose_c.error import DiagnosticEntry, VBCCompileError
from verbose_c.error.format import format_warnings
from verbose_c.fs.source_manager import SourceManager
from verbose_c.parser.lexer.tokenizer import Tokenizer
from verbose_c.preprocessor.preprocessor import Preprocessor


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("spelling, expected", [('"config.h"', 1), ('<config.h>', 2), ('HEADER', 2)])
def test_include_search_order_and_macro_headers(tmp_path, level, spelling, expected):
    """引号先查发起文件目录，尖括号和宏头文件依次查 -I 与系统目录。"""
    local, first, second, system = [tmp_path / name for name in ("source", "first", "second", "system")]
    for number, directory in enumerate((local, first, second, system), 1):
        directory.mkdir()
        (directory / "config.h").write_text(f"#define RESULT {number}\n", encoding="utf-8")
    source = local / "entry.vbc"
    source.write_text(f'#define HEADER <config.h>\n# include {spelling}\nint main() {{ return RESULT; }}', encoding="utf-8")
    options = dict(optimize_level=level, include_paths=[str(first), str(second)],
                   system_include_paths=[str(system)], log_modules=set(), dump_modules=set())
    for _ in range(2):
        result = run_source_file(str(source), **options)
        assert result.success, result.error
        assert result.exit_code == expected
    (first / "config.h").unlink()
    (second / "config.h").unlink()
    if spelling != '"config.h"':
        result = run_source_file(str(source), **options)
        assert result.success and result.exit_code == 4


def test_nested_include_searches_the_including_header_directory(tmp_path):
    """嵌套引号包含以当前头文件目录为起点，重复包含仍重复展开。"""
    headers = tmp_path / "headers"
    headers.mkdir()
    (headers / "outer.h").write_text('#include "inner.h"\n', encoding="utf-8")
    (headers / "inner.h").write_text('count += 1;\n', encoding="utf-8")
    (tmp_path / "inner.h").write_text('count += 100;\n', encoding="utf-8")
    source = tmp_path / "entry.vbc"
    source.write_text('int count = 0;\n#include <outer.h>\n#include <outer.h>\nint main() { return count; }', encoding="utf-8")
    result = run_source_file(str(source), include_paths=[str(headers)], log_modules=set(), dump_modules=set())
    assert result.success and result.exit_code == 2
    assert set(result.compilation_output.dependencies) == {str(headers / "outer.h"), str(headers / "inner.h")}


@pytest.mark.parametrize("guard", ["macro", "pragma"])
def test_guarded_recursive_includes(tmp_path, guard):
    """宏守卫和 pragma once 都能终止相互包含，且不产生伪循环警告。"""
    first, second = tmp_path / "first.h", tmp_path / "second.h"
    body = '#include "second.h"\nint value = 7;\n'
    first.write_text(('#ifndef FIRST_H\n#define FIRST_H\n' + body + '#endif\n') if guard == "macro" else '#pragma once\n' + body, encoding="utf-8")
    second.write_text('#include "first.h"\n', encoding="utf-8")
    source = tmp_path / "entry.vbc"
    source.write_text('#include "first.h"\n#include "first.h"\nint main() { return value; }', encoding="utf-8")
    result = run_source_file(str(source), log_modules=set(), dump_modules=set())
    assert result.success and result.exit_code == 7
    assert result.warning_diagnostics == []


@pytest.mark.parametrize("directive, code", [
    ('#include "missing.h"', "PP_INCLUDE_NOT_FOUND"),
    ('#include <missing.h>', "PP_INCLUDE_NOT_FOUND"),
    ('#include HEADER', "PP_INCLUDE_SYNTAX"),
    ('#include "header.h" garbage', "PP_INCLUDE_SYNTAX"),
    ('#include ""', "PP_INCLUDE_SYNTAX"),
])
def test_invalid_includes_are_errors_with_directive_location(tmp_path, capsys, directive, code):
    """缺失或畸形头文件必须编译失败，关闭警告也不能隐藏错误。"""
    source = tmp_path / "entry.vbc"
    source.write_text('\n' + directive + '\nint main() { return 0; }', encoding="utf-8")
    result = run_source_file(str(source), log_modules=set(), dump_modules=set(), show_warnings=False)
    assert not result.success and isinstance(result.error, VBCCompileError)
    entry = result.error.report.entries[0]
    assert (entry.filepath, entry.line, entry.column, entry.code, entry.severity) == (str(source), 2, 0, code, "error")
    captured = capsys.readouterr()
    assert captured.out == "" and "第 2 行" in captured.err
    assert "意外的内部错误" not in captured.err


def test_unguarded_cycles_and_cross_file_conditionals_fail(tmp_path, monkeypatch):
    """无保护循环报错，头文件不能关闭包含者的条件块。"""
    monkeypatch.setattr(Preprocessor, "MAX_INCLUDE_DEPTH", 6)
    source, header = tmp_path / "entry.vbc", tmp_path / "header.h"
    source.write_text('#if 1\n#include "header.h"\n#endif\n', encoding="utf-8")
    header.write_text('#include "header.h"\n', encoding="utf-8")
    with pytest.raises(VBCCompileError) as raised:
        compile_module(str(source))
    assert raised.value.report.entries[0].code == "PP_INCLUDE_DEPTH"
    header.write_text('#endif\n', encoding="utf-8")
    with pytest.raises(VBCCompileError) as raised:
        compile_module(str(source))
    assert raised.value.filepath == str(header) and raised.value.line == 1


def test_include_search_changes_invalidate_cached_translation_unit(tmp_path, monkeypatch):
    """搜索顺序变化或更高优先级的新文件出现时必须重编译。"""
    first, second, local = [tmp_path / name for name in ("first", "second", "source")]
    for directory in (first, second, local):
        directory.mkdir()
    (second / "value.h").write_text('#define VALUE 2\n', encoding="utf-8")
    source = local / "entry.vbc"
    source.write_text('#include <value.h>\nint main() { return VALUE; }', encoding="utf-8")
    spy = Mock(wraps=compile_module)
    monkeypatch.setattr("verbose_c.engine.engine.compile_module", spy)
    options = dict(log_modules=set(), dump_modules=set(), include_paths=[str(first), str(second)])
    assert run_source_file(str(source), **options).exit_code == 2
    assert run_source_file(str(source), **options).exit_code == 2
    assert spy.call_count == 1
    (first / "value.h").write_text('#define VALUE 1\n', encoding="utf-8")
    result = run_source_file(str(source), **options)
    assert result.success and result.exit_code == 1, result.error
    assert spy.call_count == 2
    options["include_paths"].reverse()
    assert run_source_file(str(source), **options).exit_code == 2
    assert spy.call_count == 3


def test_damaged_warning_cache_is_recompiled(tmp_path):
    """诊断缓存结构损坏时回到源码编译，避免内部格式化异常。"""
    source = tmp_path / "entry.vbc"
    source.write_text('int main() { return 7; }', encoding="utf-8")
    result = run_source_file(str(source), log_modules=set(), dump_modules=set())
    manifest_path = tmp_path / "__vbccache__" / "entry.vbb.deps.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["warning_diagnostics"] = [{"message": "损坏", "source_context": None}]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run_source_file(str(source), log_modules=set(), dump_modules=set())
    assert result.success and result.exit_code == 7


@pytest.mark.parametrize("no_warn", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_warnings_share_format_and_survive_cache_or_failure(tmp_path, capsys, no_warn, failure):
    """预处理及类型警告统一收集，成功缓存和失败路径均只显示一次。"""
    source = tmp_path / "entry.vbc"
    ending = 'return "bad";' if failure else "return n;"
    source.write_text('#define VALUE 1\n#define VALUE 2\n' + f'int main() {{ int n = 1.5; {ending} }}', encoding="utf-8")
    snapshots = []
    for iteration in range(2):
        dump = tmp_path / f"diagnostic-{iteration}.txt"
        result = run_source_file(str(source), log_modules=set(), dump_modules=set(),
                                 dump_path=str(dump), show_warnings=not no_warn)
        assert result.success == (not failure)
        entries = result.warning_diagnostics
        assert [entry.code for entry in entries] == ["PP_MACRO_REDEFINED", "CONVERSION_LOSS"]
        assert all(entry.severity == "warning" and entry.filepath == str(source) for entry in entries)
        stdout, stderr = capsys.readouterr()
        stdout = stdout.split("\n运行记录已保存到：", 1)[0]
        expected = format_warnings(entries) + "\n"
        assert stdout == ("" if no_warn else expected)
        assert ("应返回" in stderr) == failure
        assert expected in dump.read_text(encoding="utf-8")
        snapshots.append((entries, result.warnings, stdout, stderr))
    assert snapshots[0][1:] == snapshots[1][1:]


def test_preprocessor_collects_warnings_without_printing(tmp_path, capsys):
    """直接调用预处理器只得到结构化诊断，不产生终端输出。"""
    source = tmp_path / "entry.vbc"
    source.write_text('#define A 1\n#define A 2\n', encoding="utf-8")
    manager = SourceManager()
    preprocessor = Preprocessor(manager)
    preprocessor.process_tokens(Tokenizer(str(source), manager).tokens)
    assert len(preprocessor.diagnostics) == 1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("stage", ["_populate_backend_outputs", "_emit_native_outputs"])
@pytest.mark.parametrize("no_warn", [False, True])
def test_backend_failure_keeps_mixed_warnings_without_duplicates(tmp_path, capsys, monkeypatch, stage, no_warn):
    """后端前后阶段失败均保留混合警告，终端和 dump 不重复已有诊断。"""
    source, dump = tmp_path / "entry.vbc", tmp_path / "diagnostic.txt"
    source.write_text('#define VALUE 1\n#define VALUE 2\nint main() { int n = 1.5; return n; }', encoding="utf-8")
    entry = DiagnosticEntry("后端结构化警告", severity="warning", code="BACKEND_WARNING")
    failure = VBCCompileError("模拟后端错误", warnings=[entry.message, "旧接口警告"], warning_diagnostics=[entry])
    monkeypatch.setattr(f"verbose_c.engine.engine.{stage}", Mock(side_effect=failure))
    result = run_source_file(str(source), log_modules=set(), dump_modules=set(),
                             dump_path=str(dump), show_warnings=not no_warn)
    assert not result.success and result.error is failure
    assert [entry.code for entry in result.warning_diagnostics] == [
        "PP_MACRO_REDEFINED", "CONVERSION_LOSS", "BACKEND_WARNING", "COMPILER_WARNING",
    ]
    stdout, stderr = capsys.readouterr()
    assert "模拟后端错误" in stderr
    recorded = dump.read_text(encoding="utf-8")
    for entry in result.warning_diagnostics:
        assert stdout.count(entry.message) == (0 if no_warn else 1)
        assert recorded.count(entry.message) == 1
    assert "旧接口警告" in result.warnings


def test_type_diagnostics_keep_header_location_and_codes(tmp_path):
    """多文件类型错误在产生处附带行列、上下文和稳定错误码。"""
    source, header = tmp_path / "entry.vbc", tmp_path / "types.h"
    header.write_text('void first() {\n    missing;\n}\nint second() { return "bad"; }\n', encoding="utf-8")
    source.write_text('#include "types.h"\nint main() { return 0; }', encoding="utf-8")
    with pytest.raises(VBCCompileError) as raised:
        compile_module(str(source))
    entries = raised.value.report.entries
    assert len(entries) == 2
    assert [entry.line for entry in entries] == [2, 4]
    assert all(entry.filepath == str(header) and entry.column is not None for entry in entries)
    assert [entry.code for entry in entries] == ["NAME_UNDEFINED", "TYPE_MISMATCH"]
    assert all(entry.source_context and entry.severity == "error" for entry in entries)


def test_old_generated_parser_is_refreshed_for_source_locations(tmp_path, monkeypatch):
    """旧生成文件自动升级以保留 AST 文件位置，不依赖用户手动刷新。"""
    from verbose_c.engine import engine
    parser_path = tmp_path / "parser.py"
    parser_path.write_text("# 旧生成文件\n", encoding="utf-8")
    monkeypatch.setattr(engine, "default_parser_output", str(parser_path))
    assert engine.ensure_parser() is not None
    assert engine.ensure_parser() is None
    assert "VBC_PARSER_REVISION = 1" in parser_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("flag", ["-I", "-isystem"])
def test_cli_include_directories(tmp_path, flag):
    """命令行支持用户和系统搜索目录，包括含空格的路径。"""
    headers = tmp_path / "include directory"
    headers.mkdir()
    (headers / "stdio.h").write_text('#define VALUE 17\n', encoding="utf-8")
    source = tmp_path / "entry.vbc"
    source.write_text('#include <stdio.h>\nint main() { return VALUE; }', encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(source), flag, str(headers)],
                            capture_output=True, timeout=30, env={**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 17, result.stderr.decode("utf-8")
    assert result.stderr == b""
