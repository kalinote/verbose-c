import copy

from verbose_c.compiler.ast_optimizer import optimize_typed_ast
from verbose_c.compiler.enum import ScopeType, SymbolKind
from verbose_c.compiler.symbol import SymbolTable
from verbose_c.object.t_bool import VBCBool
from verbose_c.object.t_integer import VBCInteger
from verbose_c.object.t_string import VBCString
from verbose_c.parser.lexer.enum import Operator
from verbose_c.parser.parser.ast.node import (
    BinaryOpNode,
    BlockNode,
    BoolNode,
    CallNode,
    ConstantValueNode,
    CastNode,
    ExprStmtNode,
    FunctionNode,
    GetPropertyNode,
    IfNode,
    ModuleNode,
    NameNode,
    NumberNode,
    ParamNode,
    ReturnNode,
    StringNode,
    SubscriptNode,
    TypeNode,
    UnaryOpNode,
    UpdateExprNode,
    VarDeclNode,
    AssignmentNode,
    WhileNode,
    ForNode,
)
from verbose_c.typing.types import FunctionType, IntegerType, VoidType
from verbose_c.object.enum import VBCObjectType


def _global_table(*names: str) -> SymbolTable:
    table = SymbolTable(ScopeType.GLOBAL)
    for name in names:
        table.add_symbol(name, IntegerType(VBCObjectType.INT))
    return table


def _function_table(*names: str) -> SymbolTable:
    table = SymbolTable(ScopeType.FUNCTION)
    for name in names:
        table.add_symbol(name, IntegerType(VBCObjectType.INT))
    return table


def _int_decl(name: str, init):
    return VarDeclNode(TypeNode(NameNode("int")), NameNode(name), init)


def _int_type_node():
    return TypeNode(NameNode("int"))


def _optimize_expr(expr, table: SymbolTable | None = None):
    module = ModuleNode([ExprStmtNode(expr)])
    result = optimize_typed_ast(module, table or _global_table(), 1)
    return module.body[0].expr, result


def test_constant_folding_arithmetic_expression():
    expr = BinaryOpNode(
        NumberNode(1),
        Operator.ADD,
        BinaryOpNode(NumberNode(2), Operator.MULTIPLY, NumberNode(3)),
    )
    optimized, result = _optimize_expr(expr)

    assert isinstance(optimized, ConstantValueNode)
    assert isinstance(optimized.value, VBCInteger)
    assert optimized.value.value == 7
    assert result.stats.folded_constants >= 2


def test_constant_folding_integer_division_uses_runtime_semantics():
    optimized, _ = _optimize_expr(BinaryOpNode(NumberNode(10), Operator.DIVIDE, NumberNode(3)))

    assert isinstance(optimized, ConstantValueNode)
    assert isinstance(optimized.value, VBCInteger)
    assert optimized.value.value == 3


def test_constant_folding_string_comparison_and_not():
    string_expr = BinaryOpNode(StringNode('"a"'), Operator.ADD, StringNode('"b"'))
    not_expr = UnaryOpNode(Operator.NOT, NumberNode(0))

    optimized_string, _ = _optimize_expr(string_expr)
    optimized_not, _ = _optimize_expr(not_expr)

    assert isinstance(optimized_string.value, VBCString)
    assert optimized_string.value.value == "ab"
    assert isinstance(optimized_not.value, VBCInteger)
    assert optimized_not.value.value == 1


def test_constant_folding_comparison_returns_vbc_bool():
    optimized, _ = _optimize_expr(BinaryOpNode(NumberNode(1), Operator.LESS_THAN, NumberNode(2)))

    assert isinstance(optimized, ConstantValueNode)
    assert isinstance(optimized.value, VBCBool)
    assert optimized.value.value is True


def test_does_not_fold_unsafe_expressions():
    table = _global_table("p", "arr", "i", "obj")
    table.add_symbol("foo", FunctionType([], VoidType()), SymbolKind.FUNCTION)

    cases = [
        BinaryOpNode(NumberNode(1), Operator.DIVIDE, NumberNode(0)),
        BinaryOpNode(CallNode(NameNode("foo"), [], {}), Operator.ADD, NumberNode(1)),
        BinaryOpNode(UnaryOpNode(Operator.DEREFERENCE, NameNode("p")), Operator.ADD, NumberNode(1)),
        BinaryOpNode(SubscriptNode(NameNode("arr"), NameNode("i")), Operator.ADD, NumberNode(1)),
        BinaryOpNode(GetPropertyNode(NameNode("obj"), NameNode("x")), Operator.ADD, NumberNode(1)),
    ]

    for expr in cases:
        optimized, _ = _optimize_expr(expr, table)
        assert not isinstance(optimized, ConstantValueNode)


def test_constant_propagation_then_folding():
    table = _global_table("a")
    module = ModuleNode([
        _int_decl("a", NumberNode(2)),
        ReturnNode(BinaryOpNode(NameNode("a"), Operator.ADD, NumberNode(3))),
    ])

    result = optimize_typed_ast(module, table, 1)
    ret = module.body[1]

    assert isinstance(ret.value, ConstantValueNode)
    assert isinstance(ret.value.value, VBCInteger)
    assert ret.value.value.value == 5
    assert result.stats.propagated_constants == 1


def test_assignment_to_non_constant_invalidates_propagation():
    table = _global_table("a")
    table.add_symbol("read", FunctionType([], IntegerType(VBCObjectType.INT)), SymbolKind.FUNCTION)
    module = ModuleNode([
        _int_decl("a", NumberNode(2)),
        AssignmentNode(NameNode("a"), CallNode(NameNode("read"), [], {})),
        ReturnNode(NameNode("a")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[2].value, NameNode)


def test_branch_assignment_does_not_leak_constant_state():
    table = _global_table("a")
    block_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(block_table)
    module = ModuleNode([
        _int_decl("a", NumberNode(2)),
        IfNode(BoolNode("true"), BlockNode([AssignmentNode(NameNode("a"), NumberNode(3))])),
        ReturnNode(NameNode("a")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[2].value, NameNode)


def test_loop_condition_does_not_use_outer_constant_state():
    table = _global_table("i")
    body_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(body_table)
    module = ModuleNode([
        _int_decl("i", NumberNode(0)),
        WhileNode(
            BinaryOpNode(NameNode("i"), Operator.LESS_THAN, NumberNode(3)),
            BlockNode([AssignmentNode(NameNode("i"), BinaryOpNode(NameNode("i"), Operator.ADD, NumberNode(1)))]),
        ),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[1].condition, BinaryOpNode)
    assert isinstance(module.body[1].condition.left, NameNode)


def test_for_condition_does_not_use_initializer_constant_state():
    table = _global_table("i")
    for_table = SymbolTable(ScopeType.BLOCK, parent=table)
    body_table = SymbolTable(ScopeType.BLOCK, parent=for_table)
    table.add_nested_scope(for_table)
    for_table.add_nested_scope(body_table)
    module = ModuleNode([
        ForNode(
            _int_decl("i", NumberNode(0)),
            BinaryOpNode(NameNode("i"), Operator.LESS_THAN, NumberNode(3)),
            AssignmentNode(NameNode("i"), BinaryOpNode(NameNode("i"), Operator.ADD, NumberNode(1))),
            BlockNode([]),
        )
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0].condition, BinaryOpNode)
    assert isinstance(module.body[0].condition.left, NameNode)


def test_copy_propagation_replaces_simple_use():
    table = _global_table("a", "b")
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        ReturnNode(NameNode("b")),
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[2].value, NameNode)
    assert module.body[2].value.name == "a"
    assert result.stats.propagated_copies == 1


def test_copy_propagation_follows_copy_chain():
    table = _global_table("a", "b", "c")
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        _int_decl("c", NameNode("b")),
        ReturnNode(NameNode("c")),
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[3].value, NameNode)
    assert module.body[3].value.name == "a"
    assert result.stats.propagated_copies >= 2


def test_constant_propagation_takes_priority_over_copy_propagation():
    table = _global_table("a", "b")
    module = ModuleNode([
        _int_decl("a", NumberNode(2)),
        _int_decl("b", NameNode("a")),
        ReturnNode(NameNode("b")),
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[2].value, ConstantValueNode)
    assert isinstance(module.body[2].value.value, VBCInteger)
    assert module.body[2].value.value.value == 2
    assert result.stats.propagated_copies == 0


def test_writing_copy_source_invalidates_copy():
    table = _global_table("a", "b")
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        AssignmentNode(NameNode("a"), NumberNode(3)),
        ReturnNode(NameNode("b")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[3].value, NameNode)
    assert module.body[3].value.name == "b"


def test_writing_copy_target_invalidates_copy():
    table = _global_table("a", "b")
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        AssignmentNode(NameNode("b"), NumberNode(4)),
        ReturnNode(NameNode("b")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[3].value, ConstantValueNode)
    assert module.body[3].value.value.value == 4


def test_call_invalidates_global_copy_state():
    table = _global_table("a", "b")
    table.add_symbol("foo", FunctionType([], VoidType()), SymbolKind.FUNCTION)
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        ExprStmtNode(CallNode(NameNode("foo"), [], {})),
        ReturnNode(NameNode("b")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[3].value, NameNode)
    assert module.body[3].value.name == "b"


def test_indirect_write_invalidates_copy_state():
    table = _global_table("a", "b", "p")
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        AssignmentNode(UnaryOpNode(Operator.DEREFERENCE, NameNode("p")), NumberNode(1)),
        ReturnNode(NameNode("b")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[3].value, NameNode)
    assert module.body[3].value.name == "b"


def test_branch_does_not_leak_copy_state():
    table = _global_table("a", "b")
    block_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(block_table)
    module = ModuleNode([
        _int_decl("a", None),
        _int_decl("b", NameNode("a")),
        IfNode(BoolNode("true"), BlockNode([AssignmentNode(NameNode("a"), NumberNode(3))])),
        ReturnNode(NameNode("b")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[3].value, NameNode)
    assert module.body[3].value.name == "b"


def test_branch_optimization_keeps_true_branch():
    table = _global_table()
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    else_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    table.add_nested_scope(else_table)
    module = ModuleNode([
        IfNode(
            BoolNode("true"),
            BlockNode([ReturnNode(NumberNode(1))]),
            BlockNode([ReturnNode(NumberNode(2))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert module.body[0].statements[0].value.value == 1
    assert result.stats.optimized_branches == 1


def test_branch_optimization_keeps_false_branch():
    table = _global_table()
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    else_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    table.add_nested_scope(else_table)
    module = ModuleNode([
        IfNode(
            BoolNode("false"),
            BlockNode([ReturnNode(NumberNode(1))]),
            BlockNode([ReturnNode(NumberNode(2))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert module.body[0].statements[0].value.value == 2
    assert result.stats.optimized_branches == 1


def test_branch_optimization_replaces_dead_if_without_else_with_empty_block():
    table = _global_table("a")
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    module = ModuleNode([
        IfNode(BoolNode("false"), BlockNode([AssignmentNode(NameNode("a"), NumberNode(1))]))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert module.body[0].statements == []
    assert result.stats.optimized_branches == 1


def test_branch_optimization_uses_folded_condition():
    table = _global_table()
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    else_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    table.add_nested_scope(else_table)
    module = ModuleNode([
        IfNode(
            BinaryOpNode(NumberNode(1), Operator.LESS_THAN, NumberNode(2)),
            BlockNode([ReturnNode(NumberNode(1))]),
            BlockNode([ReturnNode(NumberNode(2))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert module.body[0].statements[0].value.value == 1
    assert result.stats.folded_constants >= 1
    assert result.stats.optimized_branches == 1


def test_branch_with_call_condition_is_not_optimized():
    table = _global_table()
    table.add_symbol("foo", FunctionType([], IntegerType(VBCObjectType.INT)), SymbolKind.FUNCTION)
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    else_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    table.add_nested_scope(else_table)
    module = ModuleNode([
        IfNode(
            CallNode(NameNode("foo"), [], {}),
            BlockNode([ReturnNode(NumberNode(1))]),
            BlockNode([ReturnNode(NumberNode(2))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], IfNode)
    assert result.stats.optimized_branches == 0


def test_optimized_branch_does_not_leak_constant_state():
    table = _global_table("a")
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    module = ModuleNode([
        _int_decl("a", NumberNode(2)),
        IfNode(BoolNode("true"), BlockNode([AssignmentNode(NameNode("a"), NumberNode(3))])),
        ReturnNode(NameNode("a")),
    ])

    optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[2].value, NameNode)


def test_branch_optimization_merges_identical_branches():
    table = _global_table("flag", "a")
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    else_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    table.add_nested_scope(else_table)
    module = ModuleNode([
        IfNode(
            NameNode("flag"),
            BlockNode([AssignmentNode(NameNode("a"), NumberNode(1))]),
            BlockNode([AssignmentNode(NameNode("a"), NumberNode(1))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert isinstance(module.body[0].statements[0], AssignmentNode)
    assert result.stats.optimized_branches == 1


def test_branch_optimization_keeps_identical_branches_when_condition_has_side_effects():
    table = _global_table("a")
    table.add_symbol("foo", FunctionType([], IntegerType(VBCObjectType.INT)), SymbolKind.FUNCTION)
    then_table = SymbolTable(ScopeType.BLOCK, parent=table)
    else_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(then_table)
    table.add_nested_scope(else_table)
    module = ModuleNode([
        IfNode(
            CallNode(NameNode("foo"), [], {}),
            BlockNode([AssignmentNode(NameNode("a"), NumberNode(1))]),
            BlockNode([AssignmentNode(NameNode("a"), NumberNode(1))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], IfNode)
    assert result.stats.optimized_branches == 0


def test_branch_optimization_removes_never_entered_while_loop():
    table = _global_table("a")
    body_table = SymbolTable(ScopeType.BLOCK, parent=table)
    table.add_nested_scope(body_table)
    module = ModuleNode([
        WhileNode(BoolNode("false"), BlockNode([AssignmentNode(NameNode("a"), NumberNode(1))]))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert module.body[0].statements == []
    assert result.stats.optimized_branches == 1


def test_branch_optimization_removes_for_loop_with_false_condition_but_keeps_init():
    table = _global_table()
    for_table = SymbolTable(ScopeType.BLOCK, parent=table)
    for_table.add_symbol("i", IntegerType(VBCObjectType.INT))
    body_table = SymbolTable(ScopeType.BLOCK, parent=for_table)
    table.add_nested_scope(for_table)
    for_table.add_nested_scope(body_table)
    module = ModuleNode([
        ForNode(
            _int_decl("i", NumberNode(0)),
            BoolNode("false"),
            AssignmentNode(NameNode("i"), NumberNode(1)),
            BlockNode([AssignmentNode(NameNode("i"), NumberNode(2))]),
        )
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], BlockNode)
    assert len(module.body[0].statements) == 1
    assert isinstance(module.body[0].statements[0], VarDeclNode)
    assert result.stats.optimized_branches == 1


def test_cse_extracts_repeated_return_expression():
    table = _function_table("a", "b")
    repeated = BinaryOpNode(NameNode("a"), Operator.ADD, NameNode("b"))
    module = ModuleNode([
        ReturnNode(BinaryOpNode(repeated, Operator.MULTIPLY, copy.deepcopy(repeated)))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], VarDeclNode)
    assert module.body[0].name.name.startswith("__vbc_cse_")
    assert isinstance(module.body[1], ReturnNode)
    assert isinstance(module.body[1].value.left, NameNode)
    assert isinstance(module.body[1].value.right, NameNode)
    assert module.body[1].value.left.name == module.body[0].name.name
    assert module.body[1].value.right.name == module.body[0].name.name
    assert result.stats.eliminated_common_subexpressions == 1


def test_cse_extracts_repeated_var_initializer_expression():
    table = _function_table("a", "b", "y")
    repeated = BinaryOpNode(NameNode("a"), Operator.ADD, NameNode("b"))
    module = ModuleNode([
        _int_decl("y", BinaryOpNode(repeated, Operator.ADD, copy.deepcopy(repeated)))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], VarDeclNode)
    assert module.body[0].name.name.startswith("__vbc_cse_")
    assert isinstance(module.body[1], VarDeclNode)
    assert isinstance(module.body[1].init_exp.left, NameNode)
    assert isinstance(module.body[1].init_exp.right, NameNode)
    assert module.body[1].init_exp.left.name == module.body[0].name.name
    assert module.body[1].init_exp.right.name == module.body[0].name.name
    assert result.stats.eliminated_common_subexpressions == 1


def test_cse_reuses_one_temp_for_three_repeated_expressions():
    table = _function_table("a", "b")
    repeated = BinaryOpNode(NameNode("a"), Operator.ADD, NameNode("b"))
    module = ModuleNode([
        ReturnNode(BinaryOpNode(BinaryOpNode(repeated, Operator.ADD, copy.deepcopy(repeated)), Operator.ADD, copy.deepcopy(repeated)))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert isinstance(module.body[0], VarDeclNode)
    assert result.stats.eliminated_common_subexpressions == 1
    temp_name = module.body[0].name.name
    ret_expr = module.body[1].value
    assert ret_expr.left.left.name == temp_name
    assert ret_expr.left.right.name == temp_name
    assert ret_expr.right.name == temp_name


def test_cse_skips_unsafe_repeated_expressions():
    table = _function_table("a", "b", "arr", "i", "obj", "p")
    table.add_symbol("foo", FunctionType([], IntegerType(VBCObjectType.INT)), SymbolKind.FUNCTION)
    cases = [
        BinaryOpNode(CallNode(NameNode("foo"), [], {}), Operator.ADD, CallNode(NameNode("foo"), [], {})),
        BinaryOpNode(SubscriptNode(NameNode("arr"), NameNode("i")), Operator.ADD, SubscriptNode(NameNode("arr"), NameNode("i"))),
        BinaryOpNode(GetPropertyNode(NameNode("obj"), NameNode("x")), Operator.ADD, GetPropertyNode(NameNode("obj"), NameNode("x"))),
        BinaryOpNode(UnaryOpNode(Operator.DEREFERENCE, NameNode("p")), Operator.ADD, UnaryOpNode(Operator.DEREFERENCE, NameNode("p"))),
        BinaryOpNode(UpdateExprNode(NameNode("a"), Operator.INCREMENT, False), Operator.ADD, UpdateExprNode(NameNode("a"), Operator.INCREMENT, False)),
        BinaryOpNode(
            BinaryOpNode(NameNode("a"), Operator.LOGICAL_AND, NameNode("b")),
            Operator.ADD,
            BinaryOpNode(NameNode("a"), Operator.LOGICAL_AND, NameNode("b")),
        ),
    ]

    for expr in cases:
        module = ModuleNode([ReturnNode(expr)])
        result = optimize_typed_ast(module, table, 1)
        assert len(module.body) == 1
        assert result.stats.eliminated_common_subexpressions == 0


def test_cse_skips_assignment_when_target_is_read_by_expression():
    table = _function_table("a", "b")
    repeated = BinaryOpNode(NameNode("a"), Operator.ADD, NameNode("b"))
    module = ModuleNode([
        AssignmentNode(NameNode("a"), BinaryOpNode(repeated, Operator.ADD, copy.deepcopy(repeated)))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert len(module.body) == 1
    assert isinstance(module.body[0], AssignmentNode)
    assert result.stats.eliminated_common_subexpressions == 0


def test_cse_skips_expr_statement_assignment_when_target_is_read_by_expression():
    table = _function_table("a", "b")
    repeated = BinaryOpNode(NameNode("a"), Operator.ADD, NameNode("b"))
    module = ModuleNode([
        ExprStmtNode(AssignmentNode(NameNode("a"), BinaryOpNode(repeated, Operator.ADD, copy.deepcopy(repeated))))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert len(module.body) == 1
    assert isinstance(module.body[0], ExprStmtNode)
    assert result.stats.eliminated_common_subexpressions == 0


def test_cse_does_not_run_after_constant_folding_consumes_expression():
    table = _function_table()
    repeated = BinaryOpNode(NumberNode(1), Operator.ADD, NumberNode(2))
    module = ModuleNode([
        ReturnNode(BinaryOpNode(repeated, Operator.MULTIPLY, copy.deepcopy(repeated)))
    ])

    result = optimize_typed_ast(module, table, 1)

    assert len(module.body) == 1
    assert isinstance(module.body[0].value, ConstantValueNode)
    assert result.stats.eliminated_common_subexpressions == 0


def _inline_tables():
    global_table = SymbolTable(ScopeType.GLOBAL)
    int_type = IntegerType(VBCObjectType.INT)

    add_scope = SymbolTable(ScopeType.FUNCTION, parent=global_table)
    add_scope.add_symbol("left", int_type, kind=SymbolKind.PARAMETER)
    add_scope.add_symbol("right", int_type, kind=SymbolKind.PARAMETER)
    add_body_scope = SymbolTable(ScopeType.BLOCK, parent=add_scope)
    add_scope.add_nested_scope(add_body_scope)
    add_symbol = global_table.add_symbol("add", FunctionType([int_type, int_type], int_type), SymbolKind.FUNCTION)
    add_symbol.scope = add_scope

    main_scope = SymbolTable(ScopeType.FUNCTION, parent=global_table)
    main_body_scope = SymbolTable(ScopeType.BLOCK, parent=main_scope)
    main_scope.add_nested_scope(main_body_scope)
    main_symbol = global_table.add_symbol("main", FunctionType([], int_type), SymbolKind.FUNCTION)
    main_symbol.scope = main_scope

    add_func = FunctionNode(
        _int_type_node(),
        NameNode("add"),
        [ParamNode(_int_type_node(), NameNode("left")), ParamNode(_int_type_node(), NameNode("right"))],
        {},
        BlockNode([ReturnNode(BinaryOpNode(NameNode("left"), Operator.ADD, NameNode("right")))]),
    )
    main_body = BlockNode([
        ReturnNode(CallNode(NameNode("add"), [NumberNode(1), NumberNode(2)], {}))
    ])
    main_func = FunctionNode(_int_type_node(), NameNode("main"), [], {}, main_body)
    return global_table, main_scope, add_func, main_body, main_func


def test_simple_inline_replaces_small_return_function_call():
    global_table, main_scope, add_func, main_body, main_func = _inline_tables()
    optimize_typed_ast(ModuleNode([add_func, main_func]), global_table, 1)

    result = optimize_typed_ast(main_body, main_scope, 1)

    assert result.stats.inlined_functions == 1
    assert isinstance(main_body.statements[0].value, ConstantValueNode)
    assert main_body.statements[0].value.value.value == 3


def test_simple_inline_preserves_argument_implicit_cast_boundary():
    global_table, main_scope, add_func, main_body, main_func = _inline_tables()
    arg = NumberNode(1.5)
    setattr(arg, "_implicit_cast_target", IntegerType(VBCObjectType.INT))
    main_body.statements[0] = ReturnNode(CallNode(NameNode("add"), [arg, NumberNode(2)], {}))
    optimize_typed_ast(ModuleNode([add_func, main_func]), global_table, 1)

    result = optimize_typed_ast(main_body, main_scope, 1)

    assert result.stats.inlined_functions == 1
    assert isinstance(main_body.statements[0].value.left, CastNode)


def test_simple_inline_skips_call_with_side_effect_argument():
    global_table, main_scope, add_func, main_body, main_func = _inline_tables()
    int_type = IntegerType(VBCObjectType.INT)
    read_symbol = global_table.add_symbol("read_value", FunctionType([], int_type), SymbolKind.FUNCTION)
    read_symbol.scope = SymbolTable(ScopeType.FUNCTION, parent=global_table)
    main_body.statements[0] = ReturnNode(
        CallNode(NameNode("add"), [CallNode(NameNode("read_value"), [], {}), NumberNode(2)], {})
    )
    optimize_typed_ast(ModuleNode([add_func, main_func]), global_table, 1)

    result = optimize_typed_ast(main_body, main_scope, 1)

    assert result.stats.inlined_functions == 0
    assert isinstance(main_body.statements[0].value, CallNode)


def test_simple_inline_skips_recursive_function():
    global_table = SymbolTable(ScopeType.GLOBAL)
    int_type = IntegerType(VBCObjectType.INT)
    self_scope = SymbolTable(ScopeType.FUNCTION, parent=global_table)
    self_body_scope = SymbolTable(ScopeType.BLOCK, parent=self_scope)
    self_scope.add_nested_scope(self_body_scope)
    symbol = global_table.add_symbol("self_id", FunctionType([int_type], int_type), SymbolKind.FUNCTION)
    symbol.scope = self_scope
    body = BlockNode([ReturnNode(CallNode(NameNode("self_id"), [NumberNode(1)], {}))])
    func = FunctionNode(_int_type_node(), NameNode("self_id"), [ParamNode(_int_type_node(), NameNode("value"))], {}, body)

    optimize_typed_ast(ModuleNode([func]), global_table, 1)
    result = optimize_typed_ast(body, self_scope, 1)

    assert result.stats.inlined_functions == 0
    assert isinstance(body.statements[0].value, CallNode)


def test_simple_inline_candidate_snapshot_survives_function_body_optimization():
    global_table = SymbolTable(ScopeType.GLOBAL)
    int_type = IntegerType(VBCObjectType.INT)

    square_scope = SymbolTable(ScopeType.FUNCTION, parent=global_table)
    square_scope.add_symbol("value", int_type, kind=SymbolKind.PARAMETER)
    square_body_scope = SymbolTable(ScopeType.BLOCK, parent=square_scope)
    square_scope.add_nested_scope(square_body_scope)
    square_symbol = global_table.add_symbol("square_sum", FunctionType([int_type], int_type), SymbolKind.FUNCTION)
    square_symbol.scope = square_scope

    main_scope = SymbolTable(ScopeType.FUNCTION, parent=global_table)
    main_scope.add_nested_scope(SymbolTable(ScopeType.BLOCK, parent=main_scope))
    main_symbol = global_table.add_symbol("main", FunctionType([], int_type), SymbolKind.FUNCTION)
    main_symbol.scope = main_scope

    repeated = BinaryOpNode(NameNode("value"), Operator.ADD, NumberNode(1))
    square_body = BlockNode([
        ReturnNode(BinaryOpNode(repeated, Operator.MULTIPLY, copy.deepcopy(repeated)))
    ])
    square_func = FunctionNode(
        _int_type_node(),
        NameNode("square_sum"),
        [ParamNode(_int_type_node(), NameNode("value"))],
        {},
        square_body,
    )
    main_body = BlockNode([ReturnNode(CallNode(NameNode("square_sum"), [NumberNode(2)], {}))])
    main_func = FunctionNode(_int_type_node(), NameNode("main"), [], {}, main_body)

    optimize_typed_ast(ModuleNode([square_func, main_func]), global_table, 1)
    optimize_typed_ast(square_body, square_scope, 1)
    result = optimize_typed_ast(main_body, main_scope, 1)

    assert result.stats.inlined_functions == 1
    assert isinstance(main_body.statements[0].value, ConstantValueNode)
    assert main_body.statements[0].value.value.value == 9
