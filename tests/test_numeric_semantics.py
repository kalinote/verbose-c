import pytest

from verbose_c.compiler.native.runner import can_run_native_memory
from verbose_c.compiler.opcode import Opcode
from verbose_c.engine.engine import run_bytecode_file, run_source_file
from verbose_c.object.enum import VBCObjectType
from verbose_c.object.numeric import cast_numeric
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_float import VBCFloat


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize(
    "source, expected",
    [
        ("int main() { int x = 1.9; return x * 10; }", 10),
        ("int main() { int x = 0; x = 1.9; return x * 10; }", 10),
        ("int choose(float x) { int y = x; return y * 10; }"
         "int main() { return choose(1.9); }", 10),
        ("int main() { bool x = 2; return x == true; }", 1),
        ("int main() { int x[2] = {1.9, 2.9}; return x[0] * 10 + x[1]; }", 12),
        ("int main() { float x[2] = {1, 2}; return x[0] / x[1] == 0.5; }", 1),
        ("long choose(long x) { return (long)x; }"
         "int main() { long x = 9007199254740993; return choose(x) == x; }", 1),
        ("long choose(long x) { return x / 3; }"
         "int main() { return choose(9007199254740993) == 3002399751580331; }", 1),
        ("long identity(long x) { return x; }"
         "int main() { return identity(-9223372036854775808) == -9223372036854775808; }", 1),
        ("long convert(double x) { return (long)x; }"
         "int main() { return convert(-9223372036854775808.0) == -9223372036854775808; }", 1),
        ("int main() { return (char)-128.9; }", -128),
        ("typedef int Count; int main() { return (Count)1.9; }", 1),
        ("int main() { return (int)true; }", 1),
        ("int main() { int x = 1; (void)(x = 2); return x; }", 2),
        ("int main() { int x = (int)1.9; return x * 10; }", 10),
        ("int main() { return (int)1.9 * 10; }", 10),
        ("int main() { return (int)(1.9 * 10); }", 19),
        ("int main() { return (int)(double)1.9 * 10; }", 10),
        ("int main() { return -(int)(1.9 + 2.0) * 10; }", -30),
        ("typedef int Count; int main() { return (Count)1.9 * 10; }", 10),
        ("int main() { int a = 2; int b = 3; return (a) + b * 2; }", 8),
        ("int main() { int a = 2; int b = 3; return 2 * (a) + b; }", 7),
        ("int main() { int a = 2; int b = 3; return 2 - (a) + b; }", 3),
        ("int main() { int a = 2; int b = 3; return (a) * (b) + 4; }", 10),
        ("int main() { int a = 2; int b = 3; return ((a) + b) * 2; }", 10),
        ("int main() { int a = 2; int b = 3; return (a) + (b + 1) * 2; }", 10),
        ("int main() { int a = 2; int b = 3; return (a) + b * 6 / 2; }", 11),
        ("int main() { int a = 3; return (a) - 2 * 4; }", -5),
        ("int main() { int a = 3; return 2 * (a) - 2; }", 4),
        ("int main() { int a = 3; return ((a) - 2) * 4; }", 4),
        ("int main() { int a = 3; return (a) - 0; }", 3),
        ("int main() { int a = 3; return (a) - -2; }", 5),
        ("int main() { int a = 2; int b = 3; return -(a) + b; }", 1),
        ("int main() { int a = 2; int b = 3; return -(a + b); }", -5),
        ("int main() { int a = 2; int b = 3; return !(a) + b; }", 3),
        ("int main() { double a = 1.9; int b = 10; return (int)(a) * b; }", 10),
        ("int main() { double a = 1.9; double b = 0.2; return ((int)(a) + b) * 10; }", 12),
        ("int main() { double x = 0.0; int a = 2; int b = 3; x += -(a) + b; return x; }", 1),
        ("int main() { double a = 1e16; double b = -1e16; double c = 1.0; double d = 1.0;"
         "return (a) + b * (c) + d == 1.0; }", 1),
        ("int choose(float x) { return (int)x; }"
         "int main() { return choose(1.9) * 10; }", 10),
        ("int main() { bool x = (bool)2; return (int)x; }", 1),
        ("int main() { short x = 1000; return (short)x; }", 1000),
        ("long long identity(long long x) { return (long long)x; }"
         "int main() { return identity(9007199254740993) == 9007199254740993; }", 1),
        ("int main() { unlimited int x = 18446744073709551617;"
         "return ((unlimited int)x) == 18446744073709551617; }", 1),
        ("int main() { return 2 && 3; }", 1),
        ("int main() { return 0 || 7; }", 1),
        ("int choose(int x) { return x && 3; }"
         "int main() { return choose(2); }", 1),
        ("int main() { int x = 1; return (0 && (x = 3)) || (x == 1); }", 1),
        ("int main() { bool x = true; return x + true; }", 2),
        ("int main() { bool x = true; return -x; }", -1),
        ("int main() { return true == 2; }", 0),
        ("int main() { return 2 == true; }", 0),
        ("int main() { char x = 100; char y = 100; return x + y; }", 200),
        ("int main() { short x = 1000; return x / 4; }", 250),
        ("int main() { int x = 3; float y = 2.0; return x / y == 1.5; }", 1),
        ("int main() { int x = 2; float y = 3.0; return y / x == 1.5; }", 1),
        ("int main() { int x = 1; float y = (x += 1.9); return x == 2 && y == 2.0; }", 1),
        ("int main() { char x = 100; float y = (x += 27); return x == 127 && y == 127.0; }", 1),
        ("int main() { float a = 16777216.0; int b = 1; return a + b == a; }", 1),
        ("int compare(long x) { float direct = x; double middle = x; float twice = middle; return direct > twice; }"
         "int main() { return compare(4611686293305294849); }", 1),
        ("int compare(long x) { float direct = x; double middle = x; float twice = middle; return direct < twice; }"
         "int main() { return compare(-4611686293305294849); }", 1),
        ("int main() { double a = 9007199254740992.0; long b = 1; return a + b == a; }", 1),
        ("int main() { double a = 0.1; double b = 0.2; return a + b > 0.3; }", 1),
        ("int main() { float a = 1e-40; float b = 2.0; return a * b > 0.0; }", 1),
        ("int main() { double a = 5e-324; double b = 2.0; return a * b > 0.0; }", 1),
        ("int main() { double a = -0.0; if (a) { return 0; } return !a; }", 1),
        ("int main() { bool a = -0.0; return a; }", 0),
        ("int main() { return 0 || -0.0; }", 0),
        ("float next(float x) { return x + 0.5; } int main() { return next(1.0) == 1.5; }", 1),
        ("double sum(float a, int b, double c, int d, float e, double f) { return a + b + c + d + e + f; }"
         "int main() { return (int)sum(1.25, 2, 3.5, 4, 5.25, 6.5); }", 22),
        ("double halve(int n) { if (n == 0) { return 1.0; } return 0.5 * halve(n - 1); }"
         "int main() { return halve(3) == 0.125; }", 1),
        ("float value = 1.0; void set(float x) { value = x; }"
         "int main() { set(1.5); return value == 1.5; }", 1),
        ("int main() { float a = 1.5; float b = a++; return a == 2.5 && b == 1.5; }", 1),
        ("int main() { float a = 1.5; a *= 2; return a == 3.0; }", 1),
        ("double compute(int x) { return x / 2.0; }"
         "int main() { double y = compute(3.9); return y == 1.5; }", 1),
        ("enum Values { Q = -7 / 3, R = -7 % 3, NEXT = Q + 4, NARROW = (int)1.9 };"
         "int main() { return Q == -2 && R == -1 && NEXT == 2 && NARROW == 1; }", 1),
        ("int main() { switch (-1) { case -7 % 3: return 4; default: return 0; } }", 4),
        ("int main() { switch (1) { case (int)1.9: return 4; default: return 0; } }", 4),
        ("int main() { return 0 && (1 / 0); }", 0),
        ("int main() { return 0 && (2147483647 + 1); }", 0),
        ("int main() { return 0 && (1.0 / 0.0); }", 0),
        ("int main() { int x = 300; return 0 && (char)x; }", 0),
        ("int check(int run, int a, int b) { return run && (a / b + a / b); }"
         "int main() { return check(0, 1, 0); }", 0),
        ("int stop() { _exit(0); return 0; } int sum(int a, int b) { return stop() + (a / b + a / b); }"
         "int main() { return sum(1, 0); }", 0),
    ],
)
def test_numeric_conversion_boundaries(tmp_path, optimize_level, source, expected):
    """验证优化前后的赋值、数组和函数转换边界保持相同结果。"""
    source_path = tmp_path / "numeric.vbc"
    source_path.write_text(source, encoding="utf-8")
    supports_native = "x[" not in source and "unlimited" not in source
    for native in ([False, True] if supports_native and can_run_native_memory() else [False]):
        result = run_source_file(
            str(source_path), log_modules=set(), dump_modules=set(),
            optimize_level=optimize_level, run_native_memory=native,
        )
        assert result.success, result.error
        assert result.exit_code == expected


@pytest.mark.parametrize("value", [2**53 + 1, 2**63 - 1, -(2**63)])
def test_integer_cast_preserves_full_precision(value):
    """验证大整数转换不会经过浮点数而舍入。"""
    source = VBCInteger(value, VBCObjectType.LONG)
    assert cast_numeric(source, VBCObjectType.LONGLONG).value == value


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_integer_cast_has_numeric_diagnostic(value):
    """验证非有限浮点数转整数的错误包含中文原因和转换类型。"""
    source = VBCFloat(value, VBCObjectType.NLFLOAT)
    with pytest.raises(ValueError, match="数值转换失败: 'NLFLOAT' -> 'INT'.*不能表示"):
        cast_numeric(source, VBCObjectType.INT)


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize(
    "source",
    [
        'int main() { return (int)"123"; }',
        "void nothing() {} int main() { return (int)nothing(); }",
        "int main() { int x = 1; int *p = &x; return (float)p; }",
    ],
)
def test_invalid_cast_has_compile_diagnostic(tmp_path, optimize_level, source):
    """验证不支持的转换在优化之前给出含源类型和目标类型的诊断。"""
    source_path = tmp_path / "invalid_cast.vbc"
    source_path.write_text(source, encoding="utf-8")
    result = run_source_file(
        str(source_path), log_modules=set(), dump_modules=set(),
        optimize_level=optimize_level,
    )
    assert not result.success
    assert "类型错误: 无法将类型" in str(result.error)
    assert "强制转换为" in str(result.error)
    assert "1 行" in str(result.error)


@pytest.mark.parametrize("optimize_level", [0, 1])
def test_integer_conversion_agrees_with_native_and_reloaded_bytecode(tmp_path, optimize_level):
    """验证大整数在源码、缓存、字节码重载及 native 中均不损失精度。"""
    source_path = tmp_path / "integer_cast.vbc"
    bytecode_path = tmp_path / "integer_cast.vbb"
    source_path.write_text(
        "long identity(long x) { return (long)x; }"
        "int main() { long x = 9007199254740993; return identity(x) == x; }",
        encoding="utf-8",
    )
    for _ in range(2):
        result = run_source_file(
            str(source_path), log_modules=set(), dump_modules=set(),
            output_path=str(bytecode_path), optimize_level=optimize_level,
        )
        assert result.success, result.error
        assert result.exit_code == 1
    for native in ([False, True] if can_run_native_memory() else [False]):
        result = run_bytecode_file(
            str(bytecode_path), log_modules=set(), dump_modules=set(),
            run_native_memory=native,
        )
        assert result.success, result.error
        assert result.exit_code == 1


def test_o1_folds_explicit_numeric_cast(tmp_path):
    """验证 O1 确实在编译期执行强转，且结果与 VM 运行期一致。"""
    source_path = tmp_path / "constant_cast.vbc"
    source_path.write_text("int main() { return (int)1.9; }", encoding="utf-8")
    for level in (0, 1):
        result = run_source_file(
            str(source_path), log_modules=set(), dump_modules=set(), optimize_level=level,
        )
        assert result.success, result.error
        assert result.exit_code == 1
        bytecode = result.compilation_output.function_compilation_results["main"]["bytecode"]
        assert any(instruction[0] == Opcode.CAST for instruction in bytecode) == (level == 0)


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize(
    "expression, expected",
    [("a / b", -2), ("a % b", -1), ("(-a) % (-b)", 1)],
)
def test_signed_division_and_remainder_agree_with_native(tmp_path, optimize_level, expression, expected):
    """验证带符号的商和余数在常量、函数参数、VM 和 native 中一致。"""
    for body in (
        f"int main() {{ int a = -7; int b = 3; return {expression}; }}",
        f"int compute(int a, int b) {{ return {expression}; }} int main() {{ return compute(-7, 3); }}",
    ):
        source_path = tmp_path / "division.vbc"
        source_path.write_text(body, encoding="utf-8")
        for native in ([False, True] if can_run_native_memory() else [False]):
            result = run_source_file(
                str(source_path), log_modules=set(), dump_modules=set(),
                optimize_level=optimize_level, run_native_memory=native,
            )
            assert result.success, result.error
            assert result.exit_code == expected


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ("int compute(int x) { return x + 1; } int main() { return compute(2147483647); }", "溢出"),
        ("int compute(int x) { return x - 1; } int main() { return compute(-2147483648); }", "溢出"),
        ("int compute(int x) { return x * x; } int main() { return compute(50000); }", "溢出"),
        ("int compute(int x) { return -x; } int main() { return compute(-2147483648); }", "溢出"),
        ("long compute(long x) { return x + 1; } int main() { return compute(9223372036854775807); }", "溢出|超出"),
        ("int compute(int x) { return x / -1; } int main() { return compute(-2147483648); }", "溢出"),
        ("int compute(int x) { return x % -1; } int main() { return compute(-2147483648); }", "溢出"),
        ("int compute(int x) { return 1 / x; } int main() { return compute(0); }", "除零|除数为 0"),
        ("int compute(int x) { return (char)x; } int main() { return compute(128); }", "超出范围"),
        ("int compute(long x) { return (int)x; } int main() { return compute(2147483648); }", "超出范围"),
        ("int compute(double x) { return (int)x; } int main() { return compute(2147483648.0); }", "超出范围"),
        ("long compute(double x) { return (long)x; } int main() { return compute(9223372036854775808.0); }", "数值转换失败"),
        ("float compute(double x) { return (float)x; } int main() { return compute(1e39); }", "溢出|数值转换失败"),
        ("double compute(double x) { return x * 2.0; } int main() { return compute(1e308); }", "溢出"),
        ("float compute(float x) { return x + x; } int main() { return compute(3e38); }", "溢出"),
        ("double compute(double x) { return 1.0 / x; } int main() { return compute(-0.0); }", "除零|除数为 0"),
        ("int compute(int x) { if (1 / x) { return 3; } else { return 3; } }"
         "int main() { return compute(0); }", "除零|除数为 0"),
        ("int compute(long x) { return x % -1; } int main() { return compute(-9223372036854775808); }", "溢出|超出"),
        ("int main() { char x = 127; x++; return x; }", "数值转换失败"),
        ("int main() { short x = 32767; x += 1; return x; }", "数值转换失败"),
        ("int main() { int a = 2147483647; int b = 1; int c = 1; int d = -1;"
         "return (a) + b * (c) + d; }", "溢出"),
        ("int main() { int a = -2147483648; int b = 0; return -(a) * b; }", "溢出"),
    ],
)
def test_numeric_errors_agree_with_native(tmp_path, optimize_level, source, diagnostic):
    """验证折叠及运行期的越界、溢出和除零均明确失败。"""
    import re

    source_path = tmp_path / "numeric_error.vbc"
    source_path.write_text(source, encoding="utf-8")
    for native in ([False, True] if can_run_native_memory() else [False]):
        result = run_source_file(
            str(source_path), log_modules=set(), dump_modules=set(),
            optimize_level=optimize_level, run_native_memory=native,
        )
        assert not result.success
        assert re.search(diagnostic, str(result.error)), result.error


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize("source", [
    "int main() { return (char)128; }",
    "int main() { short x = 32768; return x; }",
    "int main() { return (int)2147483648.0; }",
    "int main() { float x = 1e39; return 0; }",
    "int main() { return (int)1e309; }",
    "enum E { A = 2147483647, B }; int main() { return 0; }",
    "enum E { A = 2147483647 + 1 }; int main() { return 0; }",
])
def test_constant_numeric_errors_are_compile_diagnostics(tmp_path, optimize_level, source):
    """即使只编译，非法常量转换和枚举溢出也给出带行号的诊断。"""
    path = tmp_path / "invalid_constant.vbc"
    path.write_text(source, encoding="utf-8")
    result = run_source_file(str(path), log_modules=set(), dump_modules=set(),
                             optimize_level=optimize_level, execute=False)
    assert not result.success
    assert "1 行" in str(result.error)
    assert "溢出" in str(result.error) or "数值转换失败" in str(result.error)


@pytest.mark.parametrize("optimize_level", [0, 1])
def test_float_semantics_survive_cache_and_bytecode_reload(tmp_path, optimize_level):
    """浮点位宽和转换元数据在缓存及字节码重载后保持完整。"""
    path = tmp_path / "float_reload.vbc"
    artifact = tmp_path / "float_reload.vbb"
    path.write_text(
        "float round_step(float a, int b) { return a + b; }"
        "int main() { return round_step(16777216.0, 1) == 16777216.0; }", encoding="utf-8",
    )
    for _ in range(2):
        result = run_source_file(str(path), log_modules=set(), dump_modules=set(),
                                 output_path=str(artifact), optimize_level=optimize_level)
        assert result.success and result.exit_code == 1, result.error
    for native in ([False, True] if can_run_native_memory() else [False]):
        result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set(), run_native_memory=native)
        assert result.success and result.exit_code == 1, result.error


@pytest.mark.parametrize("optimize_level", [0, 1])
@pytest.mark.parametrize("float_type", ["float", "double"])
def test_float_comparisons_agree_across_backends(tmp_path, optimize_level, float_type):
    """用有序、相等及正负零的组合验证全部六种浮点比较指令。"""
    path = tmp_path / "float_comparisons.vbc"
    path.write_text(
        f"int compare({float_type} a, {float_type} b) {{"
        "return (a == b) + (a != b) * 2 + (a < b) * 4 + (a <= b) * 8 + (a > b) * 16 + (a >= b) * 32; }"
        "int main() { return compare(-1.0, 2.0) + compare(2.0, -1.0) * 100 + compare(-0.0, 0.0) * 10000; }",
        encoding="utf-8",
    )
    for native in ([False, True] if can_run_native_memory() else [False]):
        result = run_source_file(str(path), log_modules=set(), dump_modules=set(),
                                 optimize_level=optimize_level, run_native_memory=native)
        assert result.success and result.exit_code == 415014, result.error


def test_old_bytecode_arithmetic_version_is_rejected(tmp_path):
    """拒绝旧数值语义的字节码，避免旧折叠结果与新运行时混用。"""
    path = tmp_path / "old_semantics.vbc"
    artifact = tmp_path / "old_semantics.vbb"
    path.write_text("int main() { return -7 % 3; }", encoding="utf-8")
    result = run_source_file(str(path), log_modules=set(), dump_modules=set(), output_path=str(artifact))
    assert result.success, result.error
    data = bytearray(artifact.read_bytes())
    data[4:6] = (1).to_bytes(2, "little")
    artifact.write_bytes(data)
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    assert not result.success
    assert "字节码版本不匹配，期望 2，实际 1" in str(result.error)
