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
    ("2 > 1", True), ("MISSING", False), ("MISSING + 3 == 3", True),
    ("2 + 3 * 4 == 14", True), ("(2 + 3) * 4 == 20", True),
    ("-7 / 3 == -2 && -7 % 3 == -1", True), ("7 / -3 == -2 && 7 % -3 == 1", True),
    ("+7 - -3 == 10", True), ("~0 == -1", True),
    ("(6 & 3) == 2 && (6 | 3) == 7 && (6 ^ 3) == 5", True),
    ("1 << 2 + 1 == 8", True), ("16 >> 1 + 1 == 4", True),
    ("-3 >> 1 == -2", True), ("1 | 2 ^ 3 & 1", True),
    ("1 < 2 == 1", True), ("2 <= 2 && 3 >= 2 && 2 != 3", True),
    ("0 ? 3 : 1 ? 4 : 5", True), ("1 ? 0 ? 3 : 0 : 5", False),
    ("1 || (1 / 0)", True), ("0 && (1 / 0)", False),
    ("1 ? 7 : (1 << 99)", True), ("0 ? (1 / 0) : 7", True),
    ("(1 ? -1 : 1U) < 0", False), ("-1 < 1U", False),
    ("0xffffffffffffffff == -1", True), ("0xffffffffffffffffU + 1 == 0", True),
    ("1UL + 2lu + 3LL + 4ull == 10", True), ("077 == 63 && 0x2a == 42", True),
    ("'A' == 65 && 'AB' == 0x4142", True), (r"'\n' == 10 && '\101' == 65", True),
    (r"'\x41' == 65 && '\?' == 63", True), (r"'\xff' < 0", True),
    (r"L'\u4e2d' == 0x4e2d && U'\U0001f600' == 0x1f600", True),
    ("defined(__LINE__) && defined(__FILE__)", True),
    ("(1 ? 7 : (1, 2)) == 7", True), ("1 || (2, 3)", True),
    ("1 || (9223372036854775807 + 1)", True),
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
    "1 / 0", "1 % 0", "1 << -1", "1 >> 64", "-1 << 1",
    "9223372036854775807 + 1", "18446744073709551616U", "9223372036854775808",
    "08", "0xG", "1.5", "1e2", "1UU", "1lL", "1 ? 2", "1 ? : 2",
    "1 |", "0 && (1 +)", '"text"', "''", r"'\x'", r"'\q'",
    "(1, 2)", "1 ? (1, 2) : 3", "sizeof(int)", "CHECK(1) = 2",
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


@pytest.mark.parametrize("level", [0, 1])
def test_inactive_directives_skip_expressions_and_keep_guards(tmp_path, level):
    """非活动条件块忽略表达式和 include，宏后缀、取消定义与动态行号仍正确。"""
    source = tmp_path / "inactive.vbc"
    source.write_text(
        '#define MASK 0x10UL\n#if MASK == 16 && __LINE__ == 2\n'
        '#define ENABLED\n#endif\n#undef ENABLED\n#if defined(ENABLED)\n#error 不应选择\n'
        '#else /* 注释 */\n#if 0\n#if 1 / 0\n#elif BAD(\n#include "missing.h"\n'
        '#endif\n#endif\nint main() { return 17; }\n#endif // 注释\n', encoding="utf-8")
    result = run_source_file(str(source), optimize_level=level, log_modules=set(), dump_modules=set())
    assert result.success, result.error
    assert result.exit_code == 17
    assert result.compilation_output.dependencies == []


@pytest.mark.parametrize("level", [0, 1])
def test_directive_continuations_keep_token_boundaries(tmp_path, level):
    """续行只移除反斜杠和换行，保留空白分隔并允许指令后直接跟括号。"""
    source = tmp_path / "continuation.vbc"
    source.write_text(
        '#define ENABLED 7\n#define ALIAS \\\n ENABLED\n'
        '#if(0)\n#error 不应选择\n#elif(defined \\\n ALIAS && ALIAS == 7 && 1\\\n0 == 10)\n'
        'int main() { return 17; }\n#else\n#error 条件未生效\n#endif\n', encoding="utf-8")
    result = run_source_file(str(source), optimize_level=level, log_modules=set(), dump_modules=set())
    assert result.success, result.error
    assert result.exit_code == 17
