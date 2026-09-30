import pytest

from verbose_c.engine.engine import compile_module, run_bytecode_file, run_source_file
from verbose_c.error.exceptions import VBCCompileError
from verbose_c.object.t_null import VBCNull
from verbose_c.vm.core import VBCVirtualMachine


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("source, expected", [
    pytest.param(
        "struct Pair { int x; }; void change(struct Pair p) { p.x = 9; } "
        "int main() { struct Pair p; p.x = 1; change(p); return p.x; }", 1, id="struct-value-parameter"),
    pytest.param(
        "struct Pair { int x; }; struct Pair identity(struct Pair p) { return p; } "
        "int main() { struct Pair p; p.x = 7; return identity(p).x; }", 7, id="struct-return-field"),
    pytest.param(
        "struct Pair { int x; }; struct Pair make(int n) { struct Pair p; p.x = n; return p; } "
        "int main() { struct Pair a = make(7); struct Pair b = a; b.x = 9; return a.x; }", 7, id="struct-local-return"),
    pytest.param(
        "struct Pair { int x; }; int recurse(struct Pair p, int n) { "
        "if (n == 0) { return p.x; } p.x++; return recurse(p, n - 1); } "
        "int main() { struct Pair p; p.x = 1; int n = recurse(p, 4); return n * 10 + p.x; }", 51, id="struct-recursive-copy"),
    pytest.param(
        "struct Pair { int x; }; struct Pair p; int change() { p.x = 9; return 0; } "
        "int inspect(struct Pair value, int unused) { return value.x; } "
        "int main() { p.x = 1; return inspect(p, change()); }", 1, id="struct-copy-before-next-argument"),
    pytest.param(
        "struct Pair { int x; }; void change(struct Pair *p) { p->x = 9; } "
        "int main() { struct Pair p; p.x = 1; change(&p); return p.x; }", 9, id="struct-pointer-still-aliases"),
    pytest.param(
        "struct Pair { int x; int *p; }; void change(struct Pair value) { value.x = 9; *value.p = 8; } "
        "int main() { int n = 1; struct Pair value; value.x = 7; value.p = &n; "
        "change(value); return value.x * 10 + n; }", 78, id="struct-pointer-field-shallow-copy"),
    pytest.param(
        "struct Pair { int x; }; class Box { int value; "
        "void __init__(struct Pair p) { p.x = 9; value = p.x; } "
        "int change(struct Pair p) { p.x = 8; return p.x; } } "
        "int main() { struct Pair p; p.x = 1; Box b = new Box(p); "
        "int n = b.change(p); return b.value * 100 + n * 10 + p.x; }", 981, id="struct-constructor-method-copy"),
    pytest.param(
        "struct Pair { int x; }; class Box { struct Pair p; "
        "void __init__(struct Pair value) { p = value; } int change() { p.x++; return p.x; } } "
        "int main() { struct Pair p; p.x = 7; Box b = new Box(p); "
        "return b.change() * 10 + p.x; }", 87, id="struct-implicit-member-base"),
    pytest.param(
        "class Base { int x = 7; } class Child extends Base {} "
        "int main() { Child c = new Child(); return c.x; }", 7, id="inherited-field-initializer"),
    pytest.param(
        "class Base { int x; void __init__(int n) { x = n; } } "
        "class Middle extends Base { void __init__(int n) { super.__init__(n + 1); } } "
        "class Child extends Middle { void __init__(int n) { super.__init__(n + 1); } } "
        "int main() { Child c = new Child(5); return c.x; }", 7, id="multilevel-constructor-chain"),
    pytest.param(
        "class Base { int x = 1; int value() { return x; } } "
        "class Child extends Base { int change() { x += 2; x++; return value(); } } "
        "int main() { Child c = new Child(); return c.change(); }", 4, id="inherited-implicit-members"),
    pytest.param(
        "int x = 100; class Base { int x = 7; int value(int x) { return x + this.x; } } "
        "int main() { Base b = new Base(); return b.value(2) + x; }", 109, id="member-parameter-global-shadowing"),
    pytest.param(
        "class Base { int x = 7; int value() { int saved = x; return saved; } } "
        "int main() { Base b = new Base(); return b.value(); }", 7, id="implicit-member-copy-propagation"),
    pytest.param(
        "class Base { int x = 7; int value(int n) { x = n; int saved = x; "
        "this.x++; return saved * 10 + x; } } "
        "int main() { Base b = new Base(); return b.value(2); }", 23, id="implicit-and-explicit-member-alias"),
    pytest.param(
        "int calls = 0; int next() { calls++; return calls; } "
        "class A { int x = next(); } class B extends A {} class C extends A {} "
        "class D extends B, C { int y = next(); } "
        "int main() { D d = new D(); return d.x * 100 + d.y * 10 + calls; }", 122, id="diamond-fields-once"),
    pytest.param(
        "class A { int a = 1; } class B extends A { int b = a + 2; } "
        "class C extends A { int c = a + 4; } class D extends B, C { int d = b + c; } "
        "int main() { D d = new D(); return d.d; }", 8, id="diamond-ancestor-before-both-branches"),
    pytest.param(
        "class A { int x = 1; } class B extends A { int x = 2; } "
        "class C extends A { int x = 3; } class D extends B, C {} "
        "int main() { D d = new D(); return d.x; }", 2, id="multiple-base-field-precedence"),
    pytest.param(
        "int calls = 0; int next() { calls++; return calls; } "
        "class Base { int x = next(); void __init__() { x += 10; } } "
        "class Child extends Base { int y = next(); void __init__() { super.__init__(); } } "
        "int main() { Child c = new Child(); return c.x * 100 + c.y * 10 + calls; }", 1122, id="super-does-not-repeat-fields"),
    pytest.param(
        "class Base { int x = 1; } class Child extends Base { int x = 7; } "
        "int main() { Child a = new Child(); Child b = new Child(); a.x = 9; return b.x; }", 7, id="field-override-instance-isolation"),
    pytest.param(
        "class A { int value() { return 1; } } class B { int value() { return 2; } } "
        "class C extends A, B { int parent() { return super.value(); } } "
        "int main() { C c = new C(); return c.parent(); }", 1, id="super-first-direct-base"),
    pytest.param(
        "class Base { int x = 7; int value() { return x; } } class Child extends Base {} "
        "int main() { Child c = new Child(); Base b = (Base)c; b.x = 9; return c.value(); }", 9, id="explicit-upcast-preserves-instance"),
    pytest.param(
        "class Base { int value() { return 1; } } class Child extends Base { int value() { return 7; } } "
        "Base identity(Base b) { return b; } "
        "int main() { Child c = new Child(); Base b = identity(c); Child d = (Child)b; return d.value(); }", 7, id="implicit-upcast-and-valid-downcast"),
    pytest.param(
        "class A {} class B { int value() { return 7; } } class C extends A, B {} "
        "int main() { C c = new C(); B b = (B)c; C d = (C)b; return d.value(); }", 7, id="cast-second-base"),
    pytest.param(
        "class Base { int value() { return 7; } } typedef Base Alias; "
        "int main() { Base b = new Base(); Alias a = (Alias)b; return a.value(); }", 7, id="same-class-typedef-cast"),
])
def test_object_value_and_inheritance_semantics(tmp_path, level, source, expected):
    """验证结构体、继承及转型在 O0/O1、缓存和字节码重载中保持一致。"""
    path = tmp_path / "objects.vbc"
    artifact = tmp_path / "objects.vbb"
    path.write_text(source, encoding="utf-8")
    for _ in range(2):
        result = run_source_file(str(path), output_path=str(artifact), optimize_level=level,
                                 log_modules=set(), dump_modules=set())
        assert result.success, result.error
        assert result.exit_code == expected
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    assert result.success, result.error
    assert result.exit_code == expected
    output = result.compilation_output
    vm = VBCVirtualMachine()
    assert vm.excute(output.bytecode, output.constant_pool) == expected
    assert vm._stack.is_empty(), "对象操作不应遗留操作数"


@pytest.mark.parametrize("level", [0, 1])
def test_shadowed_field_uses_default_value_after_reload(tmp_path, level):
    """验证子类无初值的同名字段覆盖父类初值，重载后仍使用默认空值。"""
    source = tmp_path / "default_field.vbc"
    artifact = tmp_path / "default_field.vbb"
    source.write_text(
        "class Base { int x = 7; } class Child extends Base { int x; } Child c = new Child();",
        encoding="utf-8")
    result = run_source_file(str(source), output_path=str(artifact), optimize_level=level,
                             log_modules=set(), dump_modules=set())
    assert result.success, result.error
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    assert result.success, result.error
    output = result.compilation_output
    vm = VBCVirtualMachine()
    assert vm.excute(output.bytecode, output.constant_pool) == 0
    instance = vm.memory.read(vm._global_variables["c"])
    assert isinstance(instance.fields["x"], VBCNull)


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("source, message", [
    ("class A {} class B {} int main() { A a = new A(); B b = (B)a; return 0; }", "无法将类型"),
    ("class A {} class B extends A {} int main() { A a = new A(); B b = a; return 0; }", "不能将类型"),
    ("class A { void __init__(int n) {} } int main() { A a = new A(1, 2); return 0; }", "构造函数参数数量错误"),
    ("class A { int x = \"bad\"; } int main() { return 0; }", "不能将类型"),
])
def test_invalid_object_operations_fail_during_type_check(tmp_path, level, source, message):
    """验证非法转换、构造参数及字段初始化在编译期产生明确诊断。"""
    path = tmp_path / "invalid.vbc"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(VBCCompileError, match=message):
        compile_module(str(path), optimize_level=level)


@pytest.mark.parametrize("level", [0, 1])
@pytest.mark.parametrize("actual_type", ["Base", "Sibling"])
def test_invalid_downcast_checks_actual_instance_after_reload(tmp_path, level, actual_type):
    """验证静态允许的向下转换仍检查实际实例，并保留字节码中的目标类型。"""
    source = tmp_path / "bad_cast.vbc"
    artifact = tmp_path / "bad_cast.vbb"
    source.write_text(
        "class Base {} class Child extends Base {} class Sibling extends Base {} "
        f"int main() {{ Base b = new {actual_type}(); Child c = (Child)b; return 0; }}", encoding="utf-8")
    result = run_source_file(str(source), output_path=str(artifact), optimize_level=level,
                             log_modules=set(), dump_modules=set())
    assert not result.success
    assert f"实际类型 '{actual_type}' 不能转换为 'Child'" in str(result.error)
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    assert not result.success
    assert f"实际类型 '{actual_type}' 不能转换为 'Child'" in str(result.error)


@pytest.mark.parametrize("level", [0, 1])
def test_class_casts_preserve_null_after_reload(tmp_path, level):
    """验证类空引用转换后仍为空，并在重载后保留实际运行时值。"""
    source = tmp_path / "null_cast.vbc"
    artifact = tmp_path / "null_cast.vbb"
    source.write_text(
        "class Base {} class Child extends Base {} "
        "Base b = null; Child c = (Child)b; Base d = (Base)null;", encoding="utf-8")
    result = run_source_file(str(source), output_path=str(artifact), optimize_level=level,
                             log_modules=set(), dump_modules=set())
    assert result.success, result.error
    result = run_bytecode_file(str(artifact), log_modules=set(), dump_modules=set())
    assert result.success, result.error
    output = result.compilation_output
    vm = VBCVirtualMachine()
    assert vm.excute(output.bytecode, output.constant_pool) == 0
    for name in ("b", "c", "d"):
        assert isinstance(vm.memory.read(vm._global_variables[name]), VBCNull)
