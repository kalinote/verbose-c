#!/usr/bin/env python3.8
# 从 Grammar/verbose_c.gram 文件生成，用于处理 verbose-c 语法
# 生成于 2025-06-20 17:23:13

import sys

from typing import Any

# TODO: 可能需要根据实际情况动态修改
from verbose_c.parser.parser.ast.node import *
from verbose_c.parser.parser.parser import memoize, memoize_left_rec, logger, Parser
from verbose_c.parser.lexer.enum import Operator
# Keywords and soft keywords are listed at the end of the parser definition.
class GeneratedParser(Parser):

    @memoize
    def start(self) -> ModuleNode | None:
        # start: statement+
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (sl := self._loop1_1())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ModuleNode ( sl , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        return None

    @memoize
    def statement(self) -> Any | None:
        # statement: independent_block | class_definition | function_ret | pack_import | function | var_decl | var_assign | if_statement | while_statement | for_statement | expression_as_statement
        mark = self._mark()
        if (
            (independent_block := self.independent_block())
        ):
            return independent_block
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'independent_block'})
        if (
            (class_definition := self.class_definition())
        ):
            return class_definition
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'class_definition'})
        if (
            (function_ret := self.function_ret())
        ):
            return function_ret
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'function_ret'})
        if (
            (pack_import := self.pack_import())
        ):
            return pack_import
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'pack_import'})
        if (
            (function := self.function())
        ):
            return function
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'function'})
        if (
            (var_decl := self.var_decl())
        ):
            return var_decl
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'var_decl'})
        if (
            (var_assign := self.var_assign())
        ):
            return var_assign
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'var_assign'})
        if (
            (if_statement := self.if_statement())
        ):
            return if_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'if_statement'})
        if (
            (while_statement := self.while_statement())
        ):
            return while_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'while_statement'})
        if (
            (for_statement := self.for_statement())
        ):
            return for_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'for_statement'})
        if (
            (expression_as_statement := self.expression_as_statement())
        ):
            return expression_as_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'expression_as_statement'})
        return None

    @memoize
    def pack_import(self) -> PackImportNode | None:
        # pack_import: "#" 'include' include_name
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect("#"))
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"#", 'include', 'include_name'})
        return None

    @memoize
    def include_name(self) -> NameNode | StringNode | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'INCLUDE_HEADER'})
        if (
            (s := self.string())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return StringNode ( s . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'STRING'})
        if (
            (n := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( n . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        return None

    @memoize
    def function(self) -> FunctionNode | None:
        # function: type_name function_name "(" param? ")" "{" func_block "}"
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
            (fb := self.func_block())
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return FunctionNode ( a , b , c or [] , {} , fb , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'type_name', 'function_name', "(", ")", "{", 'func_block', "}"})
        return None

    @memoize
    def function_name(self) -> NameNode | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        return None

    @memoize
    def param(self) -> list [ParamNode] | None:
        # param: typed_param (("," typed_param))*
        mark = self._mark()
        if (
            (p1 := self.typed_param())
            and
            (p2 := self._loop0_2(),)
        ):
            return [p1] + ( [item [1] for item in p2] if p2 else [] )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'typed_param'})
        return None

    @memoize
    def typed_param(self) -> ParamNode | None:
        # typed_param: type_name NAME
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (t := self.type_name())
            and
            (n := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ParamNode ( t , NameNode ( n . string ) , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'type_name', 'NAME'})
        return None

    @memoize
    def independent_block(self) -> BlockNode | None:
        # independent_block: "{" func_block "}"
        mark = self._mark()
        if (
            (self.expect("{"))
            and
            (b := self.func_block())
            and
            (self.expect("}"))
        ):
            return b
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"{", 'func_block', "}"})
        return None

    @memoize
    def func_block(self) -> BlockNode | None:
        # func_block: statement*
        # nullable=True
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (b := self._loop0_3(),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BlockNode ( b or [] , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        return None

    @memoize
    def function_ret(self) -> ReturnNode | None:
        # function_ret: 'return' expr ";"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('return'))
            and
            (r := self.expr())
            and
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ReturnNode ( r , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'return', 'expr', ";"})
        return None

    @memoize
    def func_call_param(self) -> list [ASTNode] | None:
        # func_call_param: expr (("," expr))*
        mark = self._mark()
        if (
            (e1 := self.expr())
            and
            (e2 := self._loop0_4(),)
        ):
            return [e1] + ( [item [1] for item in e2] if e2 else [] )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'expr'})
        return None

    @memoize
    def var_decl(self) -> VarDeclNode | None:
        # var_decl: type_name var_name [("=" var_value)] ";"
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
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return VarDeclNode ( t , n , v [1] if v else None , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'type_name', 'var_name', ";"})
        return None

    @memoize
    def type_name(self) -> TypeNode | None:
        # type_name: (SOFT_KEYWORD | NAME) (SOFT_KEYWORD | NAME) &(NAME) | (SOFT_KEYWORD | NAME)
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (t1 := self._tmp_6())
            and
            (t2 := self._tmp_7())
            and
            (self.positive_lookahead(self.name, ))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return TypeNode ( NameNode ( t1 . string + " " + t2 . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column ) , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        if (
            (t := self._tmp_8())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return TypeNode ( NameNode ( t . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column ) , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        return None

    @memoize
    def var_name(self) -> NameNode | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        return None

    @memoize
    def var_value(self) -> Any | None:
        # var_value: expr
        mark = self._mark()
        if (
            (expr := self.expr())
        ):
            return expr
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'expr'})
        return None

    @memoize
    def var_assign(self) -> Any | None:
        # var_assign: member_expr "=" var_value ";"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (n := self.member_expr())
            and
            (self.expect("="))
            and
            (v := self.var_value())
            and
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return AssignmentNode ( n , v , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'member_expr', "=", 'var_value', ";"})
        return None

    @memoize
    def expression_as_statement(self) -> ASTNode | None:
        # expression_as_statement: expr ";"
        mark = self._mark()
        if (
            (e := self.expr())
            and
            (self.expect(";"))
        ):
            return e
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'expr', ";"})
        return None

    @memoize_left_rec
    def expr(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'expr', "||", 'logical_and'})
        if (
            (logical_and := self.logical_and())
        ):
            return logical_and
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'logical_and'})
        return None

    @memoize_left_rec
    def logical_and(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'logical_and', "&&", 'equality'})
        if (
            (equality := self.equality())
        ):
            return equality
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'equality'})
        return None

    @memoize_left_rec
    def equality(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'equality', '==', 'relational'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'equality', '!=', 'relational'})
        if (
            (relational := self.relational())
        ):
            return relational
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'relational'})
        return None

    @memoize_left_rec
    def relational(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'relational', '<', 'additive'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'relational', '<=', 'additive'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'relational', '>', 'additive'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'relational', '>=', 'additive'})
        if (
            (additive := self.additive())
        ):
            return additive
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'additive'})
        return None

    @memoize_left_rec
    def additive(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'additive', '+', 'multiplicative'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'additive', '-', 'multiplicative'})
        if (
            (multiplicative := self.multiplicative())
        ):
            return multiplicative
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'multiplicative'})
        return None

    @memoize_left_rec
    def multiplicative(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'multiplicative', '*', 'factor'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'multiplicative', '/', 'factor'})
        if (
            (factor := self.factor())
        ):
            return factor
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'factor'})
        return None

    @memoize
    def factor(self) -> Any | None:
        # factor: '(' expr ')' | unary | new_instance | member_expr
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'(', 'expr', ')'})
        if (
            (unary := self.unary())
        ):
            return unary
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'unary'})
        if (
            (new_instance := self.new_instance())
        ):
            return new_instance
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'new_instance'})
        if (
            (member_expr := self.member_expr())
        ):
            return member_expr
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'member_expr'})
        return None

    @memoize
    def unary(self) -> Any | None:
        # unary: '-' factor | '+' factor | '!' factor
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('-'))
            and
            (factor := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return UnaryOpNode ( Operator . SUBTRACT , factor , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'-', 'factor'})
        if (
            (self.expect('+'))
            and
            (factor := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return UnaryOpNode ( Operator . ADD , factor , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'+', 'factor'})
        if (
            (self.expect('!'))
            and
            (factor := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return UnaryOpNode ( Operator . NOT , factor , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'!', 'factor'})
        return None

    @memoize_left_rec
    def member_expr(self) -> Any | None:
        # member_expr: member_expr '.' NAME | member_expr '(' func_call_param? ')' | atom
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (member_expr := self.member_expr())
            and
            (self.expect('.'))
            and
            (property := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return GetPropertyNode ( member_expr , NameNode ( property . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column ) , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'member_expr', '.', 'NAME'})
        if (
            (member_expr := self.member_expr())
            and
            (self.expect('('))
            and
            (args := self.func_call_param(),)
            and
            (self.expect(')'))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return CallNode ( member_expr , args or [] , {} , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'member_expr', '(', ')'})
        if (
            (atom := self.atom())
        ):
            return atom
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'atom'})
        return None

    @memoize
    def atom(self) -> Any | None:
        # atom: ("true" | "false") | "null" | NAME | NUMBER | STRING
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (b := self._tmp_9())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BoolNode ( b . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        if (
            (self.expect("null"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NullNode ( start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"null"})
        if (
            (name := self.name())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NameNode ( name . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        if (
            (number := self.number())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NumberNode ( number . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NUMBER'})
        if (
            (string := self.string())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return StringNode ( string . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'STRING'})
        return None

    @memoize
    def if_statement(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'if', "(", 'expr', ")", "{", "}", 'else_if_barch'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'if', "(", 'expr', ")", "{", "}"})
        return None

    @memoize
    def else_if_barch(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'else', 'if', "(", 'expr', ")", "{", "}", 'else_if_barch'})
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'else', 'if', "(", 'expr', ")", "{", "}"})
        return None

    @memoize
    def else_barch(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'else', "{", "}"})
        return None

    @memoize
    def break_statement(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"break", ";"})
        return None

    @memoize
    def continue_statement(self) -> Any | None:
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
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"continue", ";"})
        return None

    @memoize
    def loop_body_statement(self) -> Any | None:
        # loop_body_statement: break_statement | continue_statement | function_ret | pack_import | function | var_decl | var_assign | if_statement | while_statement | for_statement | expression_as_statement
        mark = self._mark()
        if (
            (break_statement := self.break_statement())
        ):
            return break_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'break_statement'})
        if (
            (continue_statement := self.continue_statement())
        ):
            return continue_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'continue_statement'})
        if (
            (function_ret := self.function_ret())
        ):
            return function_ret
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'function_ret'})
        if (
            (pack_import := self.pack_import())
        ):
            return pack_import
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'pack_import'})
        if (
            (function := self.function())
        ):
            return function
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'function'})
        if (
            (var_decl := self.var_decl())
        ):
            return var_decl
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'var_decl'})
        if (
            (var_assign := self.var_assign())
        ):
            return var_assign
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'var_assign'})
        if (
            (if_statement := self.if_statement())
        ):
            return if_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'if_statement'})
        if (
            (while_statement := self.while_statement())
        ):
            return while_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'while_statement'})
        if (
            (for_statement := self.for_statement())
        ):
            return for_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'for_statement'})
        if (
            (expression_as_statement := self.expression_as_statement())
        ):
            return expression_as_statement
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'expression_as_statement'})
        return None

    @memoize
    def loop_block(self) -> BlockNode | None:
        # loop_block: loop_body_statement*
        # nullable=True
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (b := self._loop0_10(),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BlockNode ( b or [] , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        return None

    @memoize
    def while_statement(self) -> WhileNode | None:
        # while_statement: 'while' "(" expr ")" "{" loop_block "}"
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
            (b := self.loop_block())
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return WhileNode ( c , b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'while', "(", 'expr', ")", "{", 'loop_block', "}"})
        return None

    @memoize
    def for_statement(self) -> ForNode | None:
        # for_statement: 'for' "(" expr ";" expr ";" expr ")" "{" loop_block "}"
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
            (b := self.loop_block())
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ForNode ( i , c , u , b , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'for', "(", 'expr', ";", 'expr', ";", 'expr', ")", "{", 'loop_block', "}"})
        return None

    @memoize
    def class_definition(self) -> Any | None:
        # class_definition: "class" NAME "{" class_body "}"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect("class"))
            and
            (n := self.name())
            and
            (self.expect("{"))
            and
            (cb := self.class_body())
            and
            (self.expect("}"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return ClassNode ( NameNode ( n . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column ) , cb , [] , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"class", 'NAME', "{", 'class_body', "}"})
        return None

    @memoize
    def class_body(self) -> BlockNode | None:
        # class_body: ((var_decl | function))*
        # nullable=True
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (m := self._loop0_11(),)
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BlockNode ( m or [] , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则')
        return None

    @memoize
    def new_instance(self) -> NewInstanceNode | None:
        # new_instance: 'new' member_expr
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect('new'))
            and
            (c := self.member_expr())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return NewInstanceNode ( c , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'new', 'member_expr'})
        return None

    @memoize
    def _loop1_1(self) -> Any | None:
        # _loop1_1: statement
        mark = self._mark()
        children = []
        while (
            (statement := self.statement())
        ):
            children.append(statement)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop0_2(self) -> Any | None:
        # _loop0_2: ("," typed_param)
        mark = self._mark()
        children = []
        while (
            (_tmp_12 := self._tmp_12())
        ):
            children.append(_tmp_12)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop0_3(self) -> Any | None:
        # _loop0_3: statement
        mark = self._mark()
        children = []
        while (
            (statement := self.statement())
        ):
            children.append(statement)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop0_4(self) -> Any | None:
        # _loop0_4: ("," expr)
        mark = self._mark()
        children = []
        while (
            (_tmp_13 := self._tmp_13())
        ):
            children.append(_tmp_13)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _tmp_5(self) -> Any | None:
        # _tmp_5: "=" var_value
        mark = self._mark()
        if (
            (literal := self.expect("="))
            and
            (var_value := self.var_value())
        ):
            return [literal, var_value]
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"=", 'var_value'})
        return None

    @memoize
    def _tmp_6(self) -> Any | None:
        # _tmp_6: SOFT_KEYWORD | NAME
        mark = self._mark()
        if (
            (soft_keyword := self.soft_keyword())
        ):
            return soft_keyword
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'SOFT_KEYWORD'})
        if (
            (name := self.name())
        ):
            return name
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        return None

    @memoize
    def _tmp_7(self) -> Any | None:
        # _tmp_7: SOFT_KEYWORD | NAME
        mark = self._mark()
        if (
            (soft_keyword := self.soft_keyword())
        ):
            return soft_keyword
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'SOFT_KEYWORD'})
        if (
            (name := self.name())
        ):
            return name
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        return None

    @memoize
    def _tmp_8(self) -> Any | None:
        # _tmp_8: SOFT_KEYWORD | NAME
        mark = self._mark()
        if (
            (soft_keyword := self.soft_keyword())
        ):
            return soft_keyword
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'SOFT_KEYWORD'})
        if (
            (name := self.name())
        ):
            return name
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'NAME'})
        return None

    @memoize
    def _tmp_9(self) -> Any | None:
        # _tmp_9: "true" | "false"
        mark = self._mark()
        if (
            (literal := self.expect("true"))
        ):
            return literal
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"true"})
        if (
            (literal := self.expect("false"))
        ):
            return literal
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {"false"})
        return None

    @memoize
    def _loop0_10(self) -> Any | None:
        # _loop0_10: loop_body_statement
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
    def _loop0_11(self) -> Any | None:
        # _loop0_11: (var_decl | function)
        mark = self._mark()
        children = []
        while (
            (_tmp_14 := self._tmp_14())
        ):
            children.append(_tmp_14)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _tmp_12(self) -> Any | None:
        # _tmp_12: "," typed_param
        mark = self._mark()
        if (
            (literal := self.expect(","))
            and
            (typed_param := self.typed_param())
        ):
            return [literal, typed_param]
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {",", 'typed_param'})
        return None

    @memoize
    def _tmp_13(self) -> Any | None:
        # _tmp_13: "," expr
        mark = self._mark()
        if (
            (literal := self.expect(","))
            and
            (expr := self.expr())
        ):
            return [literal, expr]
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {",", 'expr'})
        return None

    @memoize
    def _tmp_14(self) -> Any | None:
        # _tmp_14: var_decl | function
        mark = self._mark()
        if (
            (var_decl := self.var_decl())
        ):
            return var_decl
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'var_decl'})
        if (
            (function := self.function())
        ):
            return function
        self._reset(mark)
        # 记录解析失败信息
        if mark >= self.error_collector.furthest_position:
            self.error_collector.add_error(mark, '无法匹配规则', {'function'})
        return None

    KEYWORDS = ('else', 'for', 'if', 'include', 'new', 'return', 'while')
    SOFT_KEYWORDS = ('break', 'class', 'continue', 'false', 'null', 'true')

if __name__ == '__main__':
    print("通过实例化 GeneratedParser 使用")
