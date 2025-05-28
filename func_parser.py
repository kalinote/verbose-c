#!/usr/bin/env python3.8
# 从 .\Grammar\verbose_c.gram 文件生成，用于处理 verbose-c 语法
# 生成于 2025-05-28 17:21:15

import sys

from typing import Any, Optional

# TODO: 需要根据实际情况动态修改
from verbose_c.parser.parser.ast.node import *
from verbose_c.parser.parser.parser import memoize, memoize_left_rec, logger, Parser
from verbose_c.parser.lexer.enum import Operator
# Keywords and soft keywords are listed at the end of the parser definition.
class GeneratedParser(Parser):

    @memoize
    def start(self) -> Optional[Any]:
        # start: func_block+
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (fb := self._loop1_1())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ModuleNode ( fb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def pack_import(self) -> Optional[Any]:
        # pack_import: "#"? 'include' include_name
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect("#"),)
            and
            (self.expect('include'))
            and
            (n := self.include_name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return PackImportNode ( n , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def include_name(self) -> Optional[NameNode]:
        # include_name: INCLUDE_HEADER | STRING | NAME
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (i := self.include_header())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( i . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (s := self.string())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return StringNode ( s . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (n := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( n . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def function(self) -> Optional[Any]:
        # function: type_name function_name "(" param? ")" "{" func_block? "}"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (a := self.type_name())
            and
            (b := self.function_name())
            and
            (self.expect("("))
            and
            (c := self.param(),)
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (fb := self.func_block(),)
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return FunctionNode ( a , b , c , None , fb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def function_name(self) -> Optional[NameNode]:
        # function_name: NAME
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (name := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( name . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def param(self) -> Optional[List [ParamNode]]:
        # param: typed_param (("," typed_param))*
        mark = self._mark()
        if (
            (p1 := self.typed_param())
            and
            (p2 := self._loop0_2(),)
        ):
            return [p1] + ( [item [1] for item in p2] if p2 else [] )
        self._reset(mark)
        return None

    @memoize
    def typed_param(self) -> Optional[ParamNode]:
        # typed_param: NAME NAME
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (t := self.name())
            and
            (n := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ParamNode ( t . string , n . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def func_block(self) -> Optional[BlockNode]:
        # func_block: ((function_ret | pack_import | function | var_decl | var_assign | if_statement | while_statement | for_statement | expression_as_statement))+
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (b := self._loop1_3())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BlockNode ( b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def function_ret(self) -> Optional[ReturnNode]:
        # function_ret: 'return' expr ";"?
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('return'))
            and
            (r := self.expr())
            and
            (self.expect(";"),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ReturnNode ( r , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def function_call(self) -> Optional[Any]:
        # function_call: function_call_expr ";"?
        mark = self._mark()
        if (
            (f := self.function_call_expr())
            and
            (self.expect(";"),)
        ):
            return f
        self._reset(mark)
        return None

    @memoize
    def function_call_expr(self) -> Optional[CallNode]:
        # function_call_expr: function_name "(" func_call_param? ")"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (n := self.function_name())
            and
            (self.expect("("))
            and
            (a := self.func_call_param(),)
            and
            (self.expect(")"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return CallNode ( n , a , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def func_call_param(self) -> Optional[List [ASTNode]]:
        # func_call_param: expr (("," expr))*
        mark = self._mark()
        if (
            (e1 := self.expr())
            and
            (e2 := self._loop0_4(),)
        ):
            return [e1] + ( [item [1] for item in e2] if e2 else [] )
        self._reset(mark)
        return None

    @memoize
    def var_decl(self) -> Optional[Any]:
        # var_decl: type_name var_name [("=" var_value)] ";"?
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (t := self.type_name())
            and
            (n := self.var_name())
            and
            (v := self._tmp_5(),)
            and
            (self.expect(";"),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return VarDeclNode ( t , n , v [1] if v else None , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def type_name(self) -> Optional[Any]:
        # type_name: SOFT_KEYWORD | NAME
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (sk := self.soft_keyword())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return TypeNode ( sk . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (n := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return TypeNode ( n . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def var_name(self) -> Optional[Any]:
        # var_name: NAME
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (name := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( name . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def var_value(self) -> Optional[Any]:
        # var_value: expr
        mark = self._mark()
        if (
            (expr := self.expr())
        ):
            return expr
        self._reset(mark)
        return None

    @memoize
    def var_assign(self) -> Optional[Any]:
        # var_assign: var_name "=" var_value ";"?
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (n := self.var_name())
            and
            (self.expect("="))
            and
            (v := self.var_value())
            and
            (self.expect(";"),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return AssignmentNode ( n , v , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def expression_as_statement(self) -> Optional[ASTNode]:
        # expression_as_statement: expr ";"?
        mark = self._mark()
        if (
            (e := self.expr())
            and
            (self.expect(";"),)
        ):
            return e
        self._reset(mark)
        return None

    @memoize_left_rec
    def expr(self) -> Optional[Any]:
        # expr: expr "||" logical_and | logical_and
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (expr := self.expr())
            and
            (self.expect("||"))
            and
            (logical_and := self.logical_and())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( expr , Operator . LOGICAL_OR , logical_and , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (logical_and := self.logical_and())
        ):
            return logical_and
        self._reset(mark)
        return None

    @memoize_left_rec
    def logical_and(self) -> Optional[Any]:
        # logical_and: logical_and "&&" equality | equality
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (logical_and := self.logical_and())
            and
            (self.expect("&&"))
            and
            (equality := self.equality())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( logical_and , Operator . LOGICAL_AND , equality , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (equality := self.equality())
        ):
            return equality
        self._reset(mark)
        return None

    @memoize_left_rec
    def equality(self) -> Optional[Any]:
        # equality: equality '==' relational | equality '!=' relational | relational
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (equality := self.equality())
            and
            (self.expect('=='))
            and
            (relational := self.relational())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( equality , Operator . EQUAL , relational , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (equality := self.equality())
            and
            (self.expect('!='))
            and
            (relational := self.relational())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( equality , Operator . NOT_EQUAL , relational , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (relational := self.relational())
        ):
            return relational
        self._reset(mark)
        return None

    @memoize_left_rec
    def relational(self) -> Optional[Any]:
        # relational: relational '<' additive | relational '<=' additive | relational '>' additive | relational '>=' additive | additive
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (relational := self.relational())
            and
            (self.expect('<'))
            and
            (additive := self.additive())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( relational , Operator . LESS_THAN , additive , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (relational := self.relational())
            and
            (self.expect('<='))
            and
            (additive := self.additive())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( relational , Operator . LESS_EQUAL , additive , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (relational := self.relational())
            and
            (self.expect('>'))
            and
            (additive := self.additive())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( relational , Operator . GREATER_THAN , additive , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (relational := self.relational())
            and
            (self.expect('>='))
            and
            (additive := self.additive())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( relational , Operator . GREATER_EQUAL , additive , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (additive := self.additive())
        ):
            return additive
        self._reset(mark)
        return None

    @memoize_left_rec
    def additive(self) -> Optional[Any]:
        # additive: additive '+' multiplicative | additive '-' multiplicative | multiplicative
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (additive := self.additive())
            and
            (self.expect('+'))
            and
            (multiplicative := self.multiplicative())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( additive , Operator . ADD , multiplicative , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (additive := self.additive())
            and
            (self.expect('-'))
            and
            (multiplicative := self.multiplicative())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( additive , Operator . SUBTRACT , multiplicative , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (multiplicative := self.multiplicative())
        ):
            return multiplicative
        self._reset(mark)
        return None

    @memoize_left_rec
    def multiplicative(self) -> Optional[Any]:
        # multiplicative: multiplicative '*' factor | multiplicative '/' factor | factor
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (multiplicative := self.multiplicative())
            and
            (self.expect('*'))
            and
            (factor := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( multiplicative , Operator . MULTIPLY , factor , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (multiplicative := self.multiplicative())
            and
            (self.expect('/'))
            and
            (factor := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( multiplicative , Operator . DIVIDE , factor , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (factor := self.factor())
        ):
            return factor
        self._reset(mark)
        return None

    @memoize
    def factor(self) -> Optional[Any]:
        # factor: '(' expr ')' | atom
        mark = self._mark()
        if (
            (self.expect('('))
            and
            (expr := self.expr())
            and
            (self.expect(')'))
        ):
            return expr
        self._reset(mark)
        if (
            (atom := self.atom())
        ):
            return atom
        self._reset(mark)
        return None

    @memoize
    def atom(self) -> Optional[Any]:
        # atom: function_call_expr | ("true" | "false") | "null" | NAME | NUMBER | STRING
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (function_call_expr := self.function_call_expr())
        ):
            return function_call_expr
        self._reset(mark)
        if (
            (b := self._tmp_6())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BoolNode ( b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (self.expect("null"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NullNode ( start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (name := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( name . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (number := self.number())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NumberNode ( number . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (string := self.string())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return StringNode ( string . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def if_statement(self) -> Optional[Any]:
        # if_statement: 'if' "(" expr ")" "{" func_block? "}" else_if_barch | 'if' "(" expr ")" "{" func_block? "}" else_barch?
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('if'))
            and
            (self.expect("("))
            and
            (c := self.expr())
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (tb := self.func_block(),)
            and
            (self.expect("}"))
            and
            (eb := self.else_if_barch())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return IfNode ( c , tb , eb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (self.expect('if'))
            and
            (self.expect("("))
            and
            (c := self.expr())
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (tb := self.func_block(),)
            and
            (self.expect("}"))
            and
            (eb := self.else_barch(),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return IfNode ( c , tb , eb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def else_if_barch(self) -> Optional[Any]:
        # else_if_barch: 'else' 'if' "(" expr ")" "{" func_block? "}" else_if_barch | 'else' 'if' "(" expr ")" "{" func_block? "}" else_barch?
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('else'))
            and
            (self.expect('if'))
            and
            (self.expect("("))
            and
            (c := self.expr())
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (tb := self.func_block(),)
            and
            (self.expect("}"))
            and
            (eb := self.else_if_barch())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return IfNode ( c , tb , eb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (self.expect('else'))
            and
            (self.expect('if'))
            and
            (self.expect("("))
            and
            (c := self.expr())
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (tb := self.func_block(),)
            and
            (self.expect("}"))
            and
            (eb := self.else_barch(),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return IfNode ( c , tb , eb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def else_barch(self) -> Optional[Any]:
        # else_barch: 'else' "{" func_block? "}"
        mark = self._mark()
        if (
            (self.expect('else'))
            and
            (self.expect("{"))
            and
            (eb := self.func_block(),)
            and
            (self.expect("}"))
        ):
            return eb
        self._reset(mark)
        return None

    @memoize
    def break_statement(self) -> Optional[Any]:
        # break_statement: "break" ";"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect("break"))
            and
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BreakNode ( start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def continue_statement(self) -> Optional[Any]:
        # continue_statement: "continue" ";"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect("continue"))
            and
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ContinueNode ( start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def loop_body_statement(self) -> Optional[Any]:
        # loop_body_statement: break_statement | continue_statement | function_ret | pack_import | function | var_decl | var_assign | if_statement | while_statement | for_statement | expression_as_statement
        mark = self._mark()
        if (
            (break_statement := self.break_statement())
        ):
            return break_statement
        self._reset(mark)
        if (
            (continue_statement := self.continue_statement())
        ):
            return continue_statement
        self._reset(mark)
        if (
            (function_ret := self.function_ret())
        ):
            return function_ret
        self._reset(mark)
        if (
            (pack_import := self.pack_import())
        ):
            return pack_import
        self._reset(mark)
        if (
            (function := self.function())
        ):
            return function
        self._reset(mark)
        if (
            (var_decl := self.var_decl())
        ):
            return var_decl
        self._reset(mark)
        if (
            (var_assign := self.var_assign())
        ):
            return var_assign
        self._reset(mark)
        if (
            (if_statement := self.if_statement())
        ):
            return if_statement
        self._reset(mark)
        if (
            (while_statement := self.while_statement())
        ):
            return while_statement
        self._reset(mark)
        if (
            (for_statement := self.for_statement())
        ):
            return for_statement
        self._reset(mark)
        if (
            (expression_as_statement := self.expression_as_statement())
        ):
            return expression_as_statement
        self._reset(mark)
        return None

    @memoize
    def loop_block(self) -> Optional[BlockNode]:
        # loop_block: loop_body_statement+
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (b := self._loop1_7())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BlockNode ( b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def while_statement(self) -> Optional[Any]:
        # while_statement: 'while' "(" expr ")" "{" loop_block? "}"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('while'))
            and
            (self.expect("("))
            and
            (c := self.expr())
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (b := self.loop_block(),)
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return WhileNode ( c , b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def for_statement(self) -> Optional[Any]:
        # for_statement: 'for' "(" expr ";" expr ";" expr ")" "{" loop_block? "}"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('for'))
            and
            (self.expect("("))
            and
            (i := self.expr())
            and
            (self.expect(";"))
            and
            (c := self.expr())
            and
            (self.expect(";"))
            and
            (u := self.expr())
            and
            (self.expect(")"))
            and
            (self.expect("{"))
            and
            (b := self.loop_block(),)
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ForNode ( i , c , u , b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def _loop1_1(self) -> Optional[Any]:
        # _loop1_1: func_block
        mark = self._mark()
        children = []
        while (
            (func_block := self.func_block())
        ):
            children.append(func_block)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop0_2(self) -> Optional[Any]:
        # _loop0_2: ("," typed_param)
        mark = self._mark()
        children = []
        while (
            (_tmp_8 := self._tmp_8())
        ):
            children.append(_tmp_8)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop1_3(self) -> Optional[Any]:
        # _loop1_3: (function_ret | pack_import | function | var_decl | var_assign | if_statement | while_statement | for_statement | expression_as_statement)
        mark = self._mark()
        children = []
        while (
            (_tmp_9 := self._tmp_9())
        ):
            children.append(_tmp_9)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop0_4(self) -> Optional[Any]:
        # _loop0_4: ("," expr)
        mark = self._mark()
        children = []
        while (
            (_tmp_10 := self._tmp_10())
        ):
            children.append(_tmp_10)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _tmp_5(self) -> Optional[Any]:
        # _tmp_5: "=" var_value
        mark = self._mark()
        if (
            (literal := self.expect("="))
            and
            (var_value := self.var_value())
        ):
            return [literal, var_value]
        self._reset(mark)
        return None

    @memoize
    def _tmp_6(self) -> Optional[Any]:
        # _tmp_6: "true" | "false"
        mark = self._mark()
        if (
            (literal := self.expect("true"))
        ):
            return literal
        self._reset(mark)
        if (
            (literal := self.expect("false"))
        ):
            return literal
        self._reset(mark)
        return None

    @memoize
    def _loop1_7(self) -> Optional[Any]:
        # _loop1_7: loop_body_statement
        mark = self._mark()
        children = []
        while (
            (loop_body_statement := self.loop_body_statement())
        ):
            children.append(loop_body_statement)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _tmp_8(self) -> Optional[Any]:
        # _tmp_8: "," typed_param
        mark = self._mark()
        if (
            (literal := self.expect(","))
            and
            (typed_param := self.typed_param())
        ):
            return [literal, typed_param]
        self._reset(mark)
        return None

    @memoize
    def _tmp_9(self) -> Optional[Any]:
        # _tmp_9: function_ret | pack_import | function | var_decl | var_assign | if_statement | while_statement | for_statement | expression_as_statement
        mark = self._mark()
        if (
            (function_ret := self.function_ret())
        ):
            return function_ret
        self._reset(mark)
        if (
            (pack_import := self.pack_import())
        ):
            return pack_import
        self._reset(mark)
        if (
            (function := self.function())
        ):
            return function
        self._reset(mark)
        if (
            (var_decl := self.var_decl())
        ):
            return var_decl
        self._reset(mark)
        if (
            (var_assign := self.var_assign())
        ):
            return var_assign
        self._reset(mark)
        if (
            (if_statement := self.if_statement())
        ):
            return if_statement
        self._reset(mark)
        if (
            (while_statement := self.while_statement())
        ):
            return while_statement
        self._reset(mark)
        if (
            (for_statement := self.for_statement())
        ):
            return for_statement
        self._reset(mark)
        if (
            (expression_as_statement := self.expression_as_statement())
        ):
            return expression_as_statement
        self._reset(mark)
        return None

    @memoize
    def _tmp_10(self) -> Optional[Any]:
        # _tmp_10: "," expr
        mark = self._mark()
        if (
            (literal := self.expect(","))
            and
            (expr := self.expr())
        ):
            return [literal, expr]
        self._reset(mark)
        return None

    KEYWORDS = ('else', 'for', 'if', 'include', 'return', 'while')
    SOFT_KEYWORDS = ('break', 'continue', 'false', 'null', 'true')


if __name__ == '__main__':
    # TODO: 需要根据实际情况动态修改
    from verbose_c.parser.parser.parser import simple_parser_main
    simple_parser_main(GeneratedParser)
