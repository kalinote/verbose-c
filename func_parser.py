#!/usr/bin/env python3.8
# 从 .\Grammar\verbose_c.gram 文件生成，用于处理 verbose-c 语法
# 生成于 2025-05-22 18:09:51

import sys

from typing import Any, Optional

# TODO: 需要根据实际情况动态修改
from verbose_c.parser.parser.ast.node import *
from verbose_c.parser.parser.parser import memoize, memoize_left_rec, logger, Parser
from verbose_c.parser.tokenizer.enum import Operator
# Keywords and soft keywords are listed at the end of the parser definition.
class GeneratedParser(Parser):

    @memoize
    def start(self) -> Optional[Any]:
        # start: pack_import
        mark = self._mark()
        if (
            (pack_import := self.pack_import())
        ):
            return pack_import
        self._reset(mark)
        return None

    @memoize
    def pack_import(self) -> Optional[Any]:
        # pack_import: "#" "include" include_name
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (self.expect("#"))
            and
            (self.expect("include"))
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
            return NameNode ( s . string , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
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
        # function: return_type function_name "(" param? ")"
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (a := self.return_type())
            and
            (b := self.function_name())
            and
            (self.expect("("))
            and
            (c := self.param(),)
            and
            (self.expect(")"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return FunctionNode ( a , b , c , None , None , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def return_type(self) -> Optional[NameNode]:
        # return_type: NAME
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
            (p2 := self._loop0_1(),)
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
    def function_call(self) -> Optional[Any]:
        # function_call: function_call_expr ";"
        mark = self._mark()
        if (
            (f := self.function_call_expr())
            and
            (self.expect(";"))
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
            (e2 := self._loop0_2(),)
        ):
            return [e1] + ( [item [1] for item in e2] if e2 else [] )
        self._reset(mark)
        return None

    @memoize
    def var_decl(self) -> Optional[Any]:
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
            (v := self._tmp_3(),)
            and
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return VarDeclNode ( t , n , v [1] if v else None , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize
    def type_name(self) -> Optional[Any]:
        # type_name: NAME
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
        # var_assign: var_name "=" var_value ";"
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
            (self.expect(";"))
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return AssignmentNode ( n , v , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        return None

    @memoize_left_rec
    def expr(self) -> Optional[Any]:
        # expr: expr '+' term | expr '-' term | term
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (expr := self.expr())
            and
            (self.expect('+'))
            and
            (term := self.term())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( expr , Operator . ADD , term , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (expr := self.expr())
            and
            (self.expect('-'))
            and
            (term := self.term())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( expr , Operator . SUBTRACT , term , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (term := self.term())
        ):
            return term
        self._reset(mark)
        return None

    @memoize_left_rec
    def term(self) -> Optional[Any]:
        # term: term '*' factor | term '/' factor | factor
        mark = self._mark()
        tok = self._tokenizer.peek()
        start_line = tok.line
        start_column = tok.column
        if (
            (l := self.term())
            and
            (self.expect('*'))
            and
            (r := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( l , Operator . MULTIPLY , r , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
        self._reset(mark)
        if (
            (term := self.term())
            and
            (self.expect('/'))
            and
            (factor := self.factor())
        ):
            tok = self._tokenizer.get_last_non_whitespace_token()
            end_line = tok.line
            end_column = tok.column
            return BinaryOpNode ( term , Operator . DIVIDE , factor , start_line=start_line, start_column=start_column, end_line=end_line, end_column=end_column )
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
            (b := self._tmp_4())
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
    def _loop0_1(self) -> Optional[Any]:
        # _loop0_1: ("," typed_param)
        mark = self._mark()
        children = []
        while (
            (_tmp_5 := self._tmp_5())
        ):
            children.append(_tmp_5)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _loop0_2(self) -> Optional[Any]:
        # _loop0_2: ("," expr)
        mark = self._mark()
        children = []
        while (
            (_tmp_6 := self._tmp_6())
        ):
            children.append(_tmp_6)
            mark = self._mark()
        self._reset(mark)
        return children

    @memoize
    def _tmp_3(self) -> Optional[Any]:
        # _tmp_3: "=" var_value
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
    def _tmp_4(self) -> Optional[Any]:
        # _tmp_4: "true" | "false"
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
    def _tmp_5(self) -> Optional[Any]:
        # _tmp_5: "," typed_param
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
    def _tmp_6(self) -> Optional[Any]:
        # _tmp_6: "," expr
        mark = self._mark()
        if (
            (literal := self.expect(","))
            and
            (expr := self.expr())
        ):
            return [literal, expr]
        self._reset(mark)
        return None

    KEYWORDS = ()
    SOFT_KEYWORDS = ('false', 'include', 'null', 'true')


if __name__ == '__main__':
    # TODO: 需要根据实际情况动态修改
    from verbose_c.parser.parser.parser import simple_parser_main
    simple_parser_main(GeneratedParser)
