import pytest

from verbose_c.engine.engine import compile_module, run_source_file
from verbose_c.error import VBCCompileError


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize("directive", ["if", "elif"])
@pytest.mark.parametrize("condition,expected", [
    ("0 || 0", False), ("0 || 1", True),
    pytest.param("1 || 0", True, id="or-true-false"), ("1 || 1", True),
    ("0 && 0", False), ("0 && 1", False), ("1 && 0", False), ("1 && 1", True),
    ("7 || 0", True), ("0 && 7", False),
    ("1 || 0 && 0", True), ("0 && 1 || 1", True),
    ("(1 || 0) && 0", False), ("!(0 && 1)", True),
    ("1 || (0 && 1) || 0", True), ("0 && (1 || 0) && 1", False),
    ("defined(ENABLED) || defined MISSING", True),
    ("defined MISSING && defined(ENABLED)", False),
    ("ENABLED || DISABLED", True), ("DISABLED && CHECK(ENABLED)", False),
    ("CHECK(ENABLED) && !defined(MISSING)", True),
    ("NESTED && (0 || CHECK(ENABLED))", True),
])
def test_preprocessor_logical_conditions(tmp_path, optimize_level, directive, condition, expected):
    """验证条件编译的真值、优先级、括号、defined 和宏展开。

    Args:
        tmp_path: 隔离的源码和缓存目录。
        optimize_level: O0 或 O1。
        directive: 待验证的 if 或 elif 指令。
        condition: 预处理逻辑表达式。
        expected: 应当选择真分支还是假分支。
    """
    prefix = "#if 0\nint main() { return 99; }\n" if directive == "elif" else ""
    source = (
        "#define ENABLED 7\n#define DISABLED 0\n"
        "#define CHECK(x) (x)\n#define NESTED (ENABLED || DISABLED)\n"
        + prefix + f"#{directive} {condition}\n"
        "int main() { return 17; }\n#else\nint main() { return 29; }\n#endif\n"
    )
    source_path = tmp_path / "condition.vbc"
    source_path.write_text(source, encoding="utf-8")
    result = run_source_file(
        str(source_path), log_modules=set(), dump_modules=set(), optimize_level=optimize_level,
    )
    assert result.success, result.error
    assert result.exit_code == (17 if expected else 29)


@pytest.mark.parametrize("directive", ["if", "elif"])
@pytest.mark.parametrize("condition", [
    "1 ||", "0 &&", "(1 ||)", "(0 &&)", "1 || (0 &&)", "0 && (1 ||)",
    "1 || (0", "0 && 1)", "1 || 0 1",
])
def test_preprocessor_rejects_incomplete_short_circuit_branches(tmp_path, directive, condition):
    """短路不能隐藏缺失操作数、括号错误或多余 token，诊断应指向指令行。"""
    prefix = "#if 0\nint main() { return 99; }\n" if directive == "elif" else ""
    source_path = tmp_path / "invalid_condition.vbc"
    source_path.write_text(
        prefix + f"#{directive} {condition}\nint main() {{ return 0; }}\n#endif\n",
        encoding="utf-8",
    )
    with pytest.raises(VBCCompileError, match="#if 表达式求值失败") as raised:
        compile_module(str(source_path))
    assert raised.value.filepath == str(source_path)
    assert raised.value.line == (3 if directive == "elif" else 1)


@pytest.mark.parametrize("optimize_level", [0, 1])
def test_nested_preprocessor_conditions_keep_only_active_dependencies(tmp_path, optimize_level):
    """验证嵌套条件只保留生效分支中的定义与 include 依赖。"""
    active_include = tmp_path / "active.inc"
    active_include.write_text("#define RESULT 17\n", encoding="utf-8")
    inactive_include = tmp_path / "inactive.inc"
    inactive_include.write_text("#define RESULT 99\n", encoding="utf-8")
    source_path = tmp_path / "nested.vbc"
    source_path.write_text(
        '#if 1 || 0\n#if 0 && 1\n#include "inactive.inc"\n'
        '#elif !defined(RESULT) && (1 || 0)\n#include "active.inc"\n'
        '#else\n#define RESULT 98\n#endif\n#else\n#define RESULT 97\n#endif\n'
        'int main() { return RESULT; }\n',
        encoding="utf-8",
    )
    result = run_source_file(
        str(source_path), log_modules=set(), dump_modules=set(), optimize_level=optimize_level,
    )
    assert result.success, result.error
    assert result.exit_code == 17
    assert result.compilation_output.dependencies == [str(active_include)]
