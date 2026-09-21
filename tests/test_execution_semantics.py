from pathlib import Path

import pytest

from verbose_c.compiler.native.runner import can_run_native_memory
from verbose_c.engine.engine import run_bytecode_file, run_source_file
from verbose_c.vm.core import VBCVirtualMachine


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize(
    "source, expected, supports_native",
    [
        pytest.param(
            "int main() { int a[3] = {10,20,30}; int *p = a; int old = (*p++)++;"
            "if (old == 10 && a[0] == 11 && a[1] == 20 && p - a == 1) { return 0; } return 99; }",
            0, False, id="dereference-postfix-target-once",
        ),
        pytest.param(
            "int calls = 0; int *pick(int *p) { calls++; return p; }"
            "int main() { int a[1] = {10}; int b[1] = {3};"
            "int value = (*pick(a) += (*pick(b) += 2));"
            "if (calls == 2 && value == 15 && a[0] == 15 && b[0] == 5) { return 0; } return 99; }",
            0, False, id="nested-lvalue-temporaries",
        ),
        pytest.param(
            "int f() { int x = 0; x = 9; return x; }"
            "int main() { return 1 + f(); }",
            10, True, id="assignment-return",
        ),
        pytest.param(
            "int f() { int x = 0; x = 9; return x; }"
            "int identity(int x) { return x; }"
            "int main() { return identity(f()); }",
            9, True, id="nested-call",
        ),
        pytest.param(
            "int value = 0; value = 9; int main() { return value + 1; }",
            10, True, id="module-assignment",
        ),
        pytest.param(
            "int main() { int a = 0; int b = 0;"
            "int value = 1 + (a = b = 9); return value; }",
            10, True, id="chained-assignment-expression",
        ),
        pytest.param(
            "int f() { int x = 0; for (int i = 0; i < 5; i++) {"
            "if (i == 2) { x = x + 1; } else { x = x + 2; } } return x; }"
            "int main() { return 1 + f(); }",
            10, True, id="loop-and-branches",
        ),
        pytest.param(
            "int f() { int x = 0; if (true) { x = 9; } return x; }"
            "int main() { return 1 + f(); }",
            10, True, id="optimized-block-assignment",
        ),
        pytest.param(
            "int main() { int a[2] = {1, 2}; a[0] = 9;"
            "return 1 + (a[1] = a[0]); }",
            10, False, id="array-assignment",
        ),
        pytest.param(
            "int main() { int a[2] = {1, 2}; int *p = a; p[0] = 9;"
            "return 1 + (p[1] = p[0]); }",
            10, False, id="pointer-subscript-assignment",
        ),
        pytest.param(
            "int main() { int x = 1; int *p = &x; *p = 9;"
            "return 1 + (*p = 9); }",
            10, False, id="pointer-assignment",
        ),
        pytest.param(
            "struct Pair { int value; };"
            "int main() { struct Pair p; p.value = 9;"
            "return 1 + (p.value = 9); }",
            10, False, id="struct-field-assignment",
        ),
        pytest.param(
            "class Box { int value; }"
            "int main() { Box box = new Box(); box.value = 9;"
            "return 1 + (box.value = 9); }",
            10, False, id="object-field-assignment",
        ),
        pytest.param(
            "void change(int *p) { *p = 9; }"
            "int main() { int x = 1; int *p = &x; change(p); return x; }",
            9, False, id="pointer-call-constant",
        ),
        pytest.param(
            "void change(int *p) { *p = 9; }"
            "int choose(int n) { int x = n; int y = x;"
            "int *p = &x; change(p); return y; }"
            "int main() { return choose(1); }",
            1, False, id="pointer-call-copy",
        ),
        pytest.param(
            "int *saved; void change() { *saved = 9; }"
            "int main() { int x = 1; saved = &x; change(); return x; }",
            9, False, id="escaped-address-call",
        ),
        pytest.param(
            "int choose(int n) { int x = 0; switch(n) {"
            "case 1: x = 10; break; case 2: x = x + 1; break;"
            "default: x = x + 20; } return x; }"
            "int main() { return choose(2); }",
            1, True, id="switch-case-entry",
        ),
        pytest.param(
            "int choose(int n) { int x = 0; switch(n) {"
            "case 1: x = 10; case 2: x = x + 1; break;"
            "default: x = x + 20; } return x; }"
            "int main() { return choose(1); }",
            11, True, id="switch-fallthrough",
        ),
        pytest.param(
            "int choose(int n) { int x = 0; switch(n) {"
            "case 1: x = 10; break; default: x = x + 20; } return x; }"
            "int main() { return choose(3); }",
            20, True, id="switch-default-entry",
        ),
        *[
            pytest.param(
                "int choose(int n) { int x = 1; "
                f"n {operator} (x = 2); return x; }}"
                f"int main() {{ return choose({argument}); }}",
                expected, True, id=f"short-circuit-{name}-{argument}",
            )
            for operator, name, argument, expected in (
                ("&&", "and", 0, 1), ("&&", "and", 1, 2),
                ("||", "or", 0, 2), ("||", "or", 1, 1),
            )
        ],
        pytest.param(
            "int choose(int n, int initial) { int x = initial; int y = x;"
            "n && (x = 9); return y; }"
            "int main() { return choose(1, 2); }",
            2, True, id="short-circuit-copy",
        ),
    ],
)
def test_execution_preserves_expression_semantics(tmp_path, optimize_level, source, expected, supports_native):
    """
    验证源码、缓存、字节码重载和原生执行的结果一致且操作数栈平衡。

    Args:
        tmp_path: 隔离的源码和产物目录。
        optimize_level: 本轮使用的优化等级。
        source: 待验证的完整程序。
        expected: 各执行路径共同的预期退出码。
        supports_native: 程序是否属于当前原生后端支持的子集。
    """
    source_path = tmp_path / "semantics.vbc"
    bytecode_path = tmp_path / "semantics.vbb"
    source_path.write_text(source, encoding="utf-8")

    for _ in range(2):
        result = run_source_file(
            str(source_path), log_modules=set(), dump_modules=set(),
            output_path=str(bytecode_path), optimize_level=optimize_level,
        )
        assert result.success, result.error
        assert result.exit_code == expected

    result = run_bytecode_file(str(bytecode_path), log_modules=set(), dump_modules=set())
    assert result.success, result.error
    assert result.exit_code == expected

    output = result.compilation_output
    vm = VBCVirtualMachine()
    assert vm.excute(
        output.bytecode, output.constant_pool, source_path=str(source_path),
        lineno_table=output.lineno_table, source_code=source.splitlines(),
    ) == expected
    assert vm._stack.is_empty(), "执行结束后不应残留赋值语句或初始化器的值"

    if supports_native and can_run_native_memory():
        native_result = run_bytecode_file(
            str(bytecode_path), log_modules=set(), dump_modules=set(), run_native_memory=True,
        )
        assert native_result.success, native_result.error
        assert native_result.exit_code == expected


@pytest.mark.parametrize("optimize_level", [0, 1])
def test_native_smoke_also_runs_on_vm(tmp_path, optimize_level):
    """验证原生综合样例在 VM、字节码重载和原生执行下均返回 99。"""
    source = Path("tests/grammar/native_mvp_smoke_test.vbc").read_text(encoding="utf-8")
    source_path = tmp_path / "smoke.vbc"
    bytecode_path = tmp_path / "smoke.vbb"
    source_path.write_text(source, encoding="utf-8")
    result = run_source_file(
        str(source_path), log_modules=set(), dump_modules=set(),
        output_path=str(bytecode_path), optimize_level=optimize_level,
    )
    assert result.success, result.error
    assert result.exit_code == 99
    result = run_bytecode_file(str(bytecode_path), log_modules=set(), dump_modules=set())
    assert result.success, result.error
    assert result.exit_code == 99
    if can_run_native_memory():
        result = run_bytecode_file(
            str(bytecode_path), log_modules=set(), dump_modules=set(), run_native_memory=True,
        )
        assert result.success, result.error
        assert result.exit_code == 99
