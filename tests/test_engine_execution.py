from types import SimpleNamespace
from unittest.mock import Mock, call

from verbose_c.engine.engine import CompilerOutput, run_bytecode_file, run_source_file
from verbose_c.engine.recorder import PipelineRecorder
from verbose_c.error import VBCCompileError, VBCRuntimeError


def test_source_and_bytecode_native_errors_use_embedded_source_path(tmp_path, capsys):
    source_path = tmp_path / "native_unsupported_array.vbc"
    bytecode_path = tmp_path / "native_unsupported_array.vbb"
    source_path.write_text(
        "int main() {\n"
        "    int values[2] = {1, 2};\n"
        "    return values[0];\n"
        "}\n",
        encoding="utf-8",
    )
    compile_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    assert compile_result.success
    capsys.readouterr()

    source_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(tmp_path / "source_native.vbb"),
        execute=False,
        run_native_memory=True,
    )
    source_output = capsys.readouterr().out
    bytecode_result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
        run_native_memory=True,
    )
    bytecode_output = capsys.readouterr().out

    expected_source_path = str(source_path.resolve())
    assert not source_result.success
    assert not bytecode_result.success
    assert source_result.exit_code == bytecode_result.exit_code == 1
    assert type(source_result.error) is type(bytecode_result.error)
    assert source_result.error.message == bytecode_result.error.message
    assert source_result.error.filepath == expected_source_path
    assert bytecode_result.error.filepath == expected_source_path
    assert "文件 None" not in source_output
    assert "文件 None" not in bytecode_output
    assert expected_source_path in source_output
    assert expected_source_path in bytecode_output


def test_bytecode_load_error_without_filepath_uses_input_path(tmp_path, monkeypatch, capsys):
    bytecode_path = tmp_path / "missing.vbb"
    monkeypatch.setattr(
        "verbose_c.engine.engine._load_bytecode_compilation_output",
        Mock(side_effect=VBCCompileError("模拟加载失败")),
    )

    result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
    )

    output = capsys.readouterr().out
    assert not result.success
    assert result.error.filepath == str(bytecode_path)
    assert f"编译错误: 文件 {bytecode_path}" in output
    assert "文件 None" not in output


def test_source_and_bytecode_compile_errors_share_warning_handling_and_ir_requirement(
    tmp_path,
    monkeypatch,
    capsys,
):
    warning = "模拟后端警告"
    source_path = tmp_path / "warning_source.vbc"
    bytecode_path = tmp_path / "warning_source.vbb"
    compilation_output = CompilerOutput(bytecode=[], constant_pool=[])

    monkeypatch.setattr(
        "verbose_c.engine.engine.IncrementalCompiler.needs_recompile",
        Mock(return_value=True),
    )
    monkeypatch.setattr(
        "verbose_c.engine.engine.compile_module",
        Mock(side_effect=VBCCompileError("模拟源码错误", warnings=[warning])),
    )
    source_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules={"ir"},
        dump_path=str(tmp_path / "source_error_dump.md"),
        execute=False,
    )
    source_output = capsys.readouterr().out

    populate_backend = Mock(side_effect=VBCCompileError("模拟字节码错误", warnings=[warning]))
    monkeypatch.setattr(
        "verbose_c.engine.engine._load_bytecode_compilation_output",
        Mock(return_value=(compilation_output, str(source_path))),
    )
    monkeypatch.setattr(
        "verbose_c.engine.engine._populate_backend_outputs",
        populate_backend,
    )
    bytecode_result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules={"ir"},
        dump_path=str(tmp_path / "bytecode_error_dump.md"),
    )
    bytecode_output = capsys.readouterr().out

    assert source_result.warnings == [warning]
    assert bytecode_result.warnings == [warning]
    assert f"警告: {warning}" in source_output
    assert f"警告: {warning}" in bytecode_output
    assert bytecode_result.error.filepath == str(source_path)
    assert populate_backend.call_args.kwargs["require_ir"] is True


def test_recorder_finalizes_once_for_success_compile_error_and_runtime_error(
    tmp_path,
    monkeypatch,
):
    source_path = str(tmp_path / "source.vbc")
    compilation_output = CompilerOutput(bytecode=[], constant_pool=[])
    vm = SimpleNamespace(memory=object())
    finalize = Mock(return_value=None)
    monkeypatch.setattr(PipelineRecorder, "finalize", finalize)
    monkeypatch.setattr(
        "verbose_c.engine.engine._load_bytecode_compilation_output",
        Mock(
            side_effect=[
                (compilation_output, source_path),
                VBCCompileError("模拟编译错误"),
                (compilation_output, source_path),
            ]
        ),
    )
    monkeypatch.setattr(
        "verbose_c.engine.engine._execute_compilation_output",
        Mock(
            side_effect=[
                (0, vm),
                VBCRuntimeError("模拟运行时错误", traceback=[]),
            ]
        ),
    )

    success_result = run_bytecode_file(
        str(tmp_path / "success.vbb"),
        log_modules=set(),
        dump_modules=set(),
    )
    compile_error_result = run_bytecode_file(
        str(tmp_path / "compile_error.vbb"),
        log_modules=set(),
        dump_modules=set(),
    )
    runtime_error_result = run_bytecode_file(
        str(tmp_path / "runtime_error.vbb"),
        log_modules=set(),
        dump_modules=set(),
    )

    assert success_result.success
    assert not compile_error_result.success
    assert not runtime_error_result.success
    assert finalize.call_count == 3
    assert finalize.call_args_list == [
        call(success=True),
        call(success=False),
        call(success=False),
    ]


def test_recorder_receives_compiled_output_once_for_each_input(tmp_path, monkeypatch):
    source_path = tmp_path / "compiled_once.vbc"
    bytecode_path = tmp_path / "compiled_once.vbb"
    source_path.write_text("int main() {\n    return 7;\n}\n", encoding="utf-8")
    on_compiled = Mock()
    monkeypatch.setattr(PipelineRecorder, "on_compiled", on_compiled)

    source_result = run_source_file(
        str(source_path),
        log_modules=set(),
        dump_modules=set(),
        output_path=str(bytecode_path),
        execute=False,
    )
    assert source_result.success
    assert on_compiled.call_count == 1

    on_compiled.reset_mock()
    monkeypatch.setattr(
        "verbose_c.engine.engine._execute_compilation_output",
        Mock(return_value=(0, SimpleNamespace(memory=object()))),
    )
    bytecode_result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
    )
    assert bytecode_result.success
    assert on_compiled.call_count == 1
