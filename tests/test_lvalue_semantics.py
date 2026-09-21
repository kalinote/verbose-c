import pytest

from verbose_c.engine.engine import run_bytecode_file, run_source_file
from verbose_c.vm.core import VBCVirtualMachine


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("operation,observed,stored", [
    ("{target} += 5", 15, 15), ("{target} -= 3", 7, 7),
    ("{target}++", 10, 11), ("++{target}", 11, 11),
    ("{target}--", 10, 9), ("--{target}", 9, 9),
])
@pytest.mark.parametrize("declarations,setup,target,counter,value,guard", [
    ("", "int a[3] = {10,20,30}; int i = 0;", "a[i++]", "i", "a[0]", "a[1] == 20"),
    ("", "int a[3] = {10,20,30}; int *p = a; int i = 0;", "p[i++]", "i", "a[0]", "a[1] == 20"),
    ("", "int a[3] = {10,20,30}; int *p = a; int i = 0;", "(*(p + i++))", "i", "a[0]", "a[1] == 20"),
    ("int calls = 0; int *pick(int *p) { calls++; return p; }",
     "int a[3] = {10,20,30};", "(*pick(a))", "calls", "a[0]", "a[1] == 20"),
    ("struct Item { int value; }; int calls = 0; struct Item *pick(struct Item *p) { calls++; return p; }",
     "struct Item item; item.value = 10;", "pick(&item)->value", "calls", "item.value", "true"),
    ("class Box { int value; } int calls = 0; Box pick(Box box) { calls++; return box; }",
     "Box box = new Box(); box.value = 10;", "pick(box).value", "calls", "box.value", "true"),
])
def test_updates_evaluate_lvalue_once(tmp_path, level, operation, observed, stored,
                                     declarations, setup, target, counter, value, guard):
    """验证带副作用的数组、指针和成员更新只计算一次目标。

    Args:
        tmp_path: 源码和字节码的隔离目录。
        level: O0 或 O1。
        operation: 复合赋值或前后自增减表达式。
        observed: 表达式应返回的值。
        stored: 目标最终保存的值。
        declarations: 辅助类型和函数声明。
        setup: 被更新的数据及副作用计数器。
        target: 带副作用的左值。
        counter: 求值次数的检查表达式。
        value: 更新结果的检查表达式。
        guard: 相邻存储不受影响的检查表达式。
    """
    source = (declarations + " int main() { " + setup
              + " int observed = (" + operation.format(target=target) + ");"
              + f" if ({counter} == 1 && observed == {observed} && {value} == {stored} && {guard}) {{ return 0; }}"
              + " return 99; }")
    path = tmp_path / "lvalue.vbc"
    artifact = tmp_path / "lvalue.vbb"
    path.write_text(source, encoding="utf-8")
    for _ in range(2):
        result = run_source_file(str(path), output_path=str(artifact), optimize_level=level,
                                 log_modules=set(), dump_modules=set())
        assert result.success, result.error
        assert result.exit_code == 0
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    assert result.success and result.exit_code == 0, result.error
    output = result.compilation_output
    vm = VBCVirtualMachine()
    assert vm.excute(output.bytecode, output.constant_pool) == 0
    assert vm._stack.is_empty(), "左值更新不应遗留操作数"
