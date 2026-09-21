import json
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from verbose_c.compiler.ir import IRLoweringError
from verbose_c.compiler.native.errors import NativeCodegenError, NativeLoweringError
from verbose_c.engine.engine import CompilerOutput, compile_module, run_bytecode_file, run_source_file
from verbose_c.engine.recorder import PipelineRecorder
from verbose_c.error import VBCCompileError, VBCRuntimeError
from verbose_c.fs.incremental_compile import IncrementalCompiler


@pytest.mark.parametrize("stage,error_type,error_field", [
    ("verbose_c.compiler.ir.lower_compiler_output_to_ir", IRLoweringError, "ir_error"),
    ("verbose_c.compiler.native.lower_ir_program_to_machine", NativeLoweringError, "machine_error"),
    ("verbose_c.compiler.native.generate_native_code", NativeCodegenError, "native_code_error"),
])
@pytest.mark.parametrize("required", [False, True])
def test_backend_expected_errors_only_fallback_when_optional(
    tmp_path, monkeypatch, stage, error_type, error_field, required,
):
    """验证已知后端限制可降级，强制生成时仍保留原始错误。"""
    source = tmp_path / "expected.vbc"
    source.write_text("int main() { return 7; }", encoding="utf-8")
    error = error_type("模拟不支持的后端能力")
    monkeypatch.setattr(stage, Mock(side_effect=error))
    if required:
        with pytest.raises(error_type) as raised:
            compile_module(str(source), require_native_code=True)
        assert raised.value is error
    else:
        output = compile_module(str(source))
        assert getattr(output, error_field) is error
        assert output.bytecode


@pytest.mark.parametrize("stage", [
    "verbose_c.compiler.ir.lower_compiler_output_to_ir",
    "verbose_c.compiler.native.lower_ir_program_to_machine",
    "verbose_c.compiler.native.generate_native_code",
])
@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, AttributeError])
@pytest.mark.parametrize("input_kind,mode", [
    ("source", "vm"), ("source", "ir"), ("source", "machine"),
    ("source", "native"), ("bytecode", "machine"), ("bytecode", "native"),
])
def test_backend_internal_errors_fail_pipeline(
    tmp_path, monkeypatch, capsys, stage, error_type, input_kind, mode,
):
    """验证内部异常在源码、字节码和强制后端路径均失败并输出 traceback。"""
    source = tmp_path / "internal.vbc"
    artifact = tmp_path / "internal.vbb"
    source.write_text("int main() { return 7; }", encoding="utf-8")
    if input_kind == "bytecode":
        prepared = run_source_file(
            str(source), log_modules=set(), dump_modules=set(),
            output_path=str(artifact), execute=False,
        )
        assert prepared.success
    error = error_type("模拟后端内部缺陷")
    monkeypatch.setattr(stage, Mock(side_effect=error))
    execute_vm = Mock()
    monkeypatch.setattr("verbose_c.engine.engine._execute_compilation_output", execute_vm)
    options = {
        "log_modules": set(),
        "dump_modules": {mode} if mode in {"ir", "machine"} else set(),
        "dump_path": str(tmp_path / "failure.md"),
        "run_native_memory": mode == "native",
    }
    if input_kind == "source":
        result = run_source_file(str(source), output_path=str(artifact), **options)
        assert not artifact.exists()
    else:
        result = run_bytecode_file(str(artifact), **options)
    captured = capsys.readouterr()
    assert not result.success
    assert result.exit_code == 1
    assert result.error is error
    assert "意外的内部错误" in captured.err
    assert "意外的内部错误" not in captured.out
    assert f"{error_type.__name__}: 模拟后端内部缺陷" in captured.err
    assert "Traceback" in captured.err
    recorded = (tmp_path / "failure.md").read_text(encoding="utf-8")
    assert captured.err in recorded
    execute_vm.assert_not_called()


def test_source_and_bytecode_native_errors_use_embedded_source_path(tmp_path, capsys):
    source_path = tmp_path / "native_unsupported_array.vbc"
    bytecode_path = tmp_path / "native_unsupported_array.vbb"
    source_path.write_text(
        "unlimited int values[2] = {1, 2};\n"
        "int main() {\n"
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
    source_output = capsys.readouterr().err
    bytecode_result = run_bytecode_file(
        str(bytecode_path),
        log_modules=set(),
        dump_modules=set(),
        run_native_memory=True,
    )
    bytecode_output = capsys.readouterr().err

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

    output = capsys.readouterr().err
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


@pytest.mark.parametrize("stored_revision", [None, 0, 3])
def test_source_recompiles_old_compiler_cache(tmp_path, monkeypatch, stored_revision):
    """
    验证旧编译器缓存会被重建，而更新后的缓存仍可复用。

    Args:
        tmp_path: 隔离的缓存目录。
        monkeypatch: 用于记录实际编译次数的测试工具。
        stored_revision: 模拟缺少修订号或修订号过期的清单。
    """
    source_path = tmp_path / "cache_revision.vbc"
    bytecode_path = tmp_path / "cache_revision.vbb"
    source_path.write_text("int main() { return 10; }", encoding="utf-8")
    result = run_source_file(
        str(source_path), log_modules=set(), dump_modules=set(), output_path=str(bytecode_path),
    )
    assert result.success

    manifest_path = bytecode_path.with_suffix(".vbb.deps.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if stored_revision is None:
        manifest.pop("compiler_revision", None)
    else:
        manifest["compiler_revision"] = stored_revision
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bytecode_path.write_bytes(b"invalid legacy bytecode")

    compile_spy = Mock(wraps=compile_module)
    monkeypatch.setattr("verbose_c.engine.engine.compile_module", compile_spy)
    for _ in range(2):
        result = run_source_file(
            str(source_path), log_modules=set(), dump_modules=set(), output_path=str(bytecode_path),
        )
        assert result.success, result.error
        assert result.exit_code == 10
        assert compile_spy.call_count == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["compiler_revision"] == IncrementalCompiler.COMPILER_REVISION
