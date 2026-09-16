import copy
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace

import pytest

from verbose_c.compiler.native import (
    NativeCodegenError, generate_native_code, native_code_program_map,
    validate_native_code_map_bytes,
)
from verbose_c.compiler.native.machine_ir import MachineOperand
from verbose_c.compiler.native.runner import (
    can_run_native_memory, run_native_bytes_in_memory, run_native_program_in_memory,
)
from verbose_c.engine.engine import compile_module, run_bytecode_file, run_source_file
from verbose_c.fs.incremental_compile import IncrementalCompiler


def _check_paths(tmp_path, source, level, *, expected=0, error=None, standalone=False, native=True):
    """核对首次编译、缓存、字节码与 Native 的执行结果。

    Args:
        tmp_path: 当前用例的独立工作目录。
        source: 待编译源码。
        level: 优化等级。
        expected: 成功执行时的退出码。
        error: 失败时必须出现的中文诊断。
        standalone: 是否导出并仅复制 exe 到空目录后运行。
        native: 是否同时验证 Native 后端。
    """
    path = tmp_path / "arrays.vbc"
    path.write_text(source, encoding="utf-8")
    artifact = tmp_path / "arrays.vbb"
    options = dict(log_modules=set(), dump_modules=set())
    results = []
    for _ in range(2):
        results.append(run_source_file(str(path), output_path=str(artifact), optimize_level=level, **options))
        assert results[-1].compilation_output is not None, results[-1].error
        assert not IncrementalCompiler().needs_recompile(str(path), str(artifact), optimize_level=level)
    results.append(run_bytecode_file(str(artifact), **options))
    if native and can_run_native_memory():
        results.append(run_source_file(str(path), output_path=str(artifact), optimize_level=level, run_native_memory=True, **options))
        results.append(run_bytecode_file(str(artifact), run_native_memory=True, **options))
    for result in results:
        assert result.success == (error is None), result.error
        assert result.exit_code == (1 if error else expected), result.error
        if error:
            assert error in str(result.error)
    if standalone:
        executable = tmp_path / "arrays.exe"
        compiled = subprocess.run([sys.executable, "-m", "verbose_c.cli", str(path), f"-O{level}", "--emit-exe", str(executable)],
                                  capture_output=True, timeout=30, env={**os.environ, "PYTHONUTF8": "1"})
        assert compiled.returncode == 0, compiled.stderr.decode("utf-8")
        if can_run_native_memory():
            isolated = tmp_path / "isolated"
            isolated.mkdir()
            copied = isolated / executable.name
            shutil.copy2(executable, copied)
            completed = subprocess.run([str(copied)], capture_output=True, timeout=10, cwd=isolated)
            assert list(isolated.iterdir()) == [copied]
            assert completed.returncode == (1 if error else expected), completed.stderr.decode("utf-8")
            assert completed.stdout == b""
            assert (error in completed.stderr.decode("utf-8")) if error else completed.stderr == b""
    return results[0]


@pytest.mark.parametrize("level", [0, 1])
def test_array_updates_evaluate_target_once(tmp_path, level):
    """更新表达式只计算一次下标，且分别保留新值、旧值与实际写入位置。"""
    _check_paths(tmp_path, """
int calls = 0;
int next_index() { return calls++; }
int main() {
    int values[6] = {10, 20, 30, 40, 50, 60};
    int i = 0;
    int a = (values[i++] += 5);
    int b = values[i++]++;
    int c = ++values[i++];
    calls = 3;
    int d = (values[next_index()] -= 5);
    int e = values[next_index()]--;
    int f = --values[next_index()];
    if (i != 3 || calls != 6) { return 97; }
    if (a != 15 || b != 20 || c != 31 || d != 35 || e != 50 || f != 59) { return 98; }
    if (values[0] != 15 || values[1] != 21 || values[2] != 31 || values[3] != 35 || values[4] != 49 || values[5] != 59) { return 99; }
    return 0;
}
""", level, standalone=True)


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("type_name,value", [
    ("char", "120"), ("short", "32000"), ("int", "2000000000"),
    ("long", "2147483648"), ("long long", "2147483649"),
    ("bool", "true"), ("float", "1.25"), ("double", "2.5"),
])
def test_array_scalar_initialization_and_store(tmp_path, level, type_name, value):
    """各标量类型支持清零、部分初始化、完整初始化及首尾读写。"""
    _check_paths(tmp_path, f"""
int main() {{
    {type_name} zero[3];
    {type_name} partial[3] = {{{value}}};
    {type_name} full[2] = {{{value}, {value}}};
    int last = 2;
    zero[last] = full[1];
    if (zero[0] == ({type_name})0 && zero[1] == ({type_name})0 && zero[last] == {value}
        && partial[0] == {value} && partial[last] == ({type_name})0 && full[0] == {value}) {{ return 0; }}
    return 99;
}}
""", level)


@pytest.mark.parametrize("level", [0, 1])
def test_array_float_rounding_and_update(tmp_path, level):
    """数组 float 存储和更新保持 binary32 舍入，double 保留更高精度。"""
    _check_paths(tmp_path, """
int main() {
    float values[2] = {16777217.0, 1.5};
    double wide[2] = {16777217.0, 2.25};
    values[1] += 0.25;
    double previous = wide[1]++;
    if (values[0] == 16777216.0 && values[1] == 1.75 && wide[0] == 16777217.0 && previous == 2.25 && wide[1] == 3.25) { return 0; }
    return 99;
}
""", level, standalone=True)


@pytest.mark.parametrize("level", [0, 1])
def test_nested_array_updates_keep_temporary_slots_distinct(tmp_path, level):
    """嵌套数组下标更新、块变量及 switch 临时槽互不覆盖。"""
    _check_paths(tmp_path, """
int main() {
    int a[3] = {10, 20, 30};
    int indices[2] = {0, 1};
    int i = 0;
    {
        int later[2] = {4, 5};
        a[indices[i++]++] += later[1];
        switch (i) {
            case 1: a[indices[i++]++]++; break;
            default: return 98;
        }
        if (later[0] != 4 || later[1] != 5) { return 97; }
    }
    if (i == 2 && indices[0] == 1 && indices[1] == 2 && a[0] == 15 && a[1] == 21 && a[2] == 30) { return 0; }
    return 99;
}
""", level)


@pytest.mark.parametrize("level", [0, 1])
def test_arrays_are_isolated_across_recursion_blocks_and_loop_declarations(tmp_path, level):
    """递归调用拥有独立数组，嵌套块不重叠，每次循环声明重新清零。"""
    _check_paths(tmp_path, """
int sum(int n) {
    int saved[2] = {n, 9};
    if (n == 0) { return saved[0]; }
    int child = sum(n - 1);
    return saved[0] + child;
}
int main() {
    int outer[2] = {8, 9};
    int count = 0;
    for (int i = 0; i < 4; i++) {
        int fresh[2];
        int partial[2] = {i};
        if (fresh[0] != 0 || fresh[1] != 0 || partial[1] != 0) { return 98; }
        fresh[0] = 100;
        fresh[1] = 200;
        partial[1] = 300;
        count += partial[0];
        { int inner[2] = {30, 40}; count += inner[1]; }
    }
    if (count == 166 && outer[0] == 8 && outer[1] == 9 && sum(8) == 36) { return 0; }
    return 99;
}
""", level, standalone=True)


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("index", ["-1", "2", "9223372036854775807"])
@pytest.mark.parametrize("operation", ["return values[index];", "values[index] = 3; return 0;"])
def test_array_bounds_fail_before_memory_access(tmp_path, level, index, operation):
    """负数、等长和极大下标在读取及写入前均返回可传播的中文错误。"""
    _check_paths(tmp_path, f"""
int access(long index) {{
    int values[2] = {{1, 2}};
    {operation}
}}
int main() {{ return access({index}); }}
""", level, error="数组下标越界", standalone=True)


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("body", [
    "char a[1] = {number(128)}; return 0;",
    "short a[1]; a[0] = number(32768); return 0;",
    "char a[1] = {127}; a[0]++; return 0;",
    "int a[1] = {2147483647}; a[0] += 1; return 0;",
])
def test_array_element_conversion_and_overflow(tmp_path, level, body):
    """数组初始化、写入和更新沿用定宽整数转换与溢出检查。"""
    _check_paths(tmp_path, f"int number(int n) {{ return n; }} int main() {{ {body} }}", level,
                 error="超出范围" if "2147483647" not in body else "整数溢出")


@pytest.mark.parametrize("source,reason", [
    ("int a[2]; int main() { return a[0]; }", "全局数组"),
    ("int main() { string a[2]; return 0; }", "数组元素"),
    ("int main() { unlimited int a[2]; return 0; }", "数组元素"),
    ("int get(int *p) { return 0; } int main() { int a[2]; return get(a); }", "array_decay"),
    ("int *get() { int a[2]; return a; } int main() { return 0; }", "数组地址"),
    ("int main() { int a[2]; int *p = &a[0]; return 0; }", "array_decay"),
    ("int main() { int a[1000000000]; return 0; }", "栈帧"),
    ("int main() { int a[250]; int b[250]; int c[250]; return a[0]+b[0]+c[0]; }", "栈帧"),
])
def test_arrays_outside_native_scope_have_source_diagnostics(tmp_path, capsys, source, reason):
    """范围外数组与超大栈帧在生成机器码前明确拒绝并保留源码位置。"""
    path = tmp_path / "unsupported.vbc"
    path.write_text(source, encoding="utf-8")
    result = run_source_file(str(path), execute=False, run_native_memory=True, log_modules=set(), dump_modules=set())
    captured = capsys.readouterr()
    assert not result.success and result.exit_code == 1
    assert reason in captured.err and str(path) in captured.err and "行 1" in captured.err
    assert "意外的内部错误" not in captured.err


@pytest.fixture
def array_program(tmp_path):
    """编译多数组程序供 Machine IR 与产物损坏校验复用。"""
    path = tmp_path / "layout.vbc"
    path.write_text("int main() { int a[3] = {1, 2, 3}; int b[2] = {4, 5}; return a[2]+b[1]; }", encoding="utf-8")
    return compile_module(str(path), require_native_code=True)


@pytest.mark.parametrize("damage", ["address", "length", "type", "size", "escape", "initialization", "duplicate"])
def test_machine_array_provenance_cannot_be_forged(array_program, damage):
    """普通整数、错误数组来源及初始化前的访问不能进入机器码。"""
    machine = copy.deepcopy(array_program.machine_program)
    function = machine.functions["main"]
    nodes = [node for block in function.blocks for node in block.instructions]
    load = next(node for node in nodes if node.op == "load_index")
    if damage == "address":
        load.args[0] = MachineOperand.imm(123)
    elif damage == "length":
        load.attrs["length"] += 1
    elif damage == "type":
        load.args[0] = replace(load.args[0], value=replace(load.args[0].value, element_type="DOUBLE"))
    elif damage == "size":
        function.frame.array_slots[0] = replace(function.frame.array_slots[0], size=8)
    elif damage == "escape":
        function.blocks[-1].terminator.args = [load.args[0]]
    elif damage == "initialization":
        block = function.blocks[0]
        block.instructions.remove(load)
        block.instructions.insert(0, load)
    else:
        function.frame.array_slots.append(function.frame.array_slots[0])
    with pytest.raises(NativeCodegenError, match="数组"):
        generate_native_code(machine)


def test_array_native_map_roundtrip(array_program, tmp_path):
    """导出并重载机器码和 map 后仍能检查并执行数组。"""
    program = array_program.native_code_program
    metadata = native_code_program_map(program)
    binary = tmp_path / "arrays.bin"
    mapping = tmp_path / "arrays.map.json"
    binary.write_bytes(program.code)
    mapping.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    reloaded = json.loads(mapping.read_text(encoding="utf-8"))
    validate_native_code_map_bytes(binary.read_bytes(), reloaded)
    main = next(item for item in reloaded["functions"] if item["name"] == "main")
    assert [(slot["array_length"], slot["element_type"]) for slot in main["stack_slots"] if "array_length" in slot] == [(3, "INT"), (2, "INT")]
    if can_run_native_memory():
        assert run_native_bytes_in_memory(binary.read_bytes(), reloaded) == 8


def test_array_entry_can_own_global_frame(tmp_path):
    """直接函数入口的全局帧序言可与局部数组共存。"""
    path = tmp_path / "owned.vbc"
    path.write_text("int shared = 1; int main() { shared = 7; int a[2] = {1, 2}; return a[1] + shared; }", encoding="utf-8")
    machine = compile_module(str(path), require_native_code=True).machine_program
    machine.module = machine.functions["main"]
    program = generate_native_code(machine)
    metadata = native_code_program_map(program)
    validate_native_code_map_bytes(program.code, metadata)
    if can_run_native_memory():
        assert run_native_program_in_memory(program) == 9


@pytest.mark.parametrize("damage", ["overlap", "offset", "frame", "frame_shrink", "length", "origin"])
def test_array_map_rejects_corrupted_layout(array_program, damage):
    """拒绝偏移重叠、超栈帧以及清单与数组来源不一致的产物。"""
    metadata = native_code_program_map(array_program.native_code_program)
    main = next(item for item in metadata["functions"] if item["name"] == "main")
    arrays = [slot for slot in main["stack_slots"] if "array_length" in slot]
    if damage == "overlap":
        arrays[0]["offset"] = arrays[1]["offset"] - 8
    elif damage == "offset":
        arrays[0]["offset"] -= 8
    elif damage == "frame":
        main["frame_size"] += 16
    elif damage == "frame_shrink":
        main["frame_size"] -= 16
    elif damage == "length":
        arrays[0]["array_length"] += 1
    else:
        next(item for item in main["instructions"] if item["source_op"] == "array_load")["source_attrs"]["array_slot"] = "array[999]"
    with pytest.raises(NativeCodegenError):
        validate_native_code_map_bytes(array_program.native_code_program.code, metadata)


def test_array_memory_runner_rejects_corrupted_offset(array_program):
    """内存执行入口也必须校验数组布局。"""
    program = copy.deepcopy(array_program.native_code_program)
    function = program.functions["main"]
    index = next(index for index, slot in enumerate(function.stack_slots) if slot.array_length is not None)
    function.stack_slots[index] = replace(function.stack_slots[index], offset=8)
    with pytest.raises(NativeCodegenError, match="数组|栈帧槽|栈槽"):
        run_native_program_in_memory(program)


@pytest.mark.parametrize("level", [0, 1])
def test_other_lvalue_updates_preserve_existing_semantics(tmp_path, level):
    """保存数组目标不影响普通变量、指针解引用和结构体字段的更新。"""
    _check_paths(tmp_path, """
struct Item { int value; };
int main() {
    int value = 4;
    int *p = &value;
    struct Item item;
    item.value = 10;
    int old = p[0]++;
    int changed = (item.value += 2);
    int current = ++item.value;
    value += 3;
    if (old == 4 && value == 8 && changed == 12 && current == 13 && item.value == 13) { return 0; }
    return 99;
}
""", level, native=False)


@pytest.mark.parametrize("level", [0, 1])
def test_vm_global_array_update_still_evaluates_index_once(tmp_path, level):
    """VM 全局数组也复用更新目标，Native 限制不影响已有执行路径。"""
    _check_paths(tmp_path, """
int a[3] = {10, 20, 30};
int i = 0;
a[i++] += 5;
a[i++]++;
++a[i++];
int main() {
    if (i == 3 && a[0] == 15 && a[1] == 21 && a[2] == 31) { return 0; }
    return 99;
}
""", level, native=False)
