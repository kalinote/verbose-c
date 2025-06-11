import argparse
import ast
import sys
import time
import traceback
from abc import abstractmethod
from typing import Any, Callable, ClassVar, Dict, Optional, Tuple, Type, TypeVar, cast

from verbose_c.parser.parser.ast.node import ASTNode
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.tokenizer import Mark, Tokenizer
from verbose_c.parser.lexer.token import Token

T = TypeVar("T")
P = TypeVar("P", bound="Parser")
F = TypeVar("F", bound=Callable[..., Any])


def logger(method: F) -> F:
    """For non-memoized functions that we want to be logged.

    (In practice this is only non-leader left-recursive functions.)
    """
    method_name = method.__name__

    def logger_wrapper(self: P, *args: object) -> F:
        argsr = ",".join(repr(arg) for arg in args)
        fill = "  " * self._level
        print(f"{fill}{method_name}({argsr}) .... (looking at {self.showpeek()})")
        self._level += 1
        tree = method(self, *args)
        self._level -= 1
        print(f"{fill}... {method_name}({argsr}) --> {tree!s:.200}")
        return tree

    logger_wrapper.__wrapped__ = method  # type: ignore
    return cast(F, logger_wrapper)


def memoize(method: F) -> F:
    """Memoize a symbol method."""
    method_name = method.__name__

    def memoize_wrapper(self: P, *args: object) -> F:
        mark = self._mark()
        key = mark, method_name, args
        
        if key in self._cache:
            # 命中缓存
            tree, endmark = self._cache[key]
            self._reset(endmark)
            return tree
        
        if key not in self._cache:
            self._level += 1
            tree = method(self, *args)
            self._level -= 1
            endmark = self._mark()
            self._cache[key] = tree, endmark
        else:
            tree, endmark = self._cache[key]
            self._reset(endmark)
        return tree

    memoize_wrapper.__wrapped__ = method  # type: ignore
    return cast(F, memoize_wrapper)


def memoize_left_rec(method: Callable[[P], Optional[T]]) -> Callable[[P], Optional[T]]:
    """Memoize a left-recursive symbol method."""
    method_name = method.__name__

    def memoize_left_rec_wrapper(self: P) -> Optional[T]:
        mark = self._mark()
        key = mark, method_name, ()
        
        if key in self._cache:
            # 命中缓存
            tree, endmark = self._cache[key]
            self._reset(endmark)
            return tree

        if key not in self._cache:
            self._level += 1

            # For left-recursive rules we manipulate the cache and
            # loop until the rule shows no progress, then pick the
            # previous result.  For an explanation why this works, see
            # https://github.com/PhilippeSigaud/Pegged/wiki/Left-Recursion
            # (But we use the memoization cache instead of a static
            # variable; perhaps this is similar to a paper by Warth et al.
            # (http://web.cs.ucla.edu/~todd/research/pub.php?id=pepm08).

            # Prime the cache with a failure.
            self._cache[key] = None, mark
            lastresult, lastmark = None, mark
            depth = 0

            while True:
                self._reset(mark)
                self.in_recursive_rule += 1
                try:
                    result = method(self)
                finally:
                    self.in_recursive_rule -= 1
                endmark = self._mark()
                depth += 1
                if not result:
                    break
                if endmark <= lastmark:
                    break
                self._cache[key] = lastresult, lastmark = result, endmark

            self._reset(lastmark)
            tree = lastresult

            self._level -= 1
            if tree:
                endmark = self._mark()
            else:
                endmark = mark
                self._reset(endmark)
            self._cache[key] = tree, endmark
        else:
            tree, endmark = self._cache[key]
            if tree:
                self._reset(endmark)
        return tree

    memoize_left_rec_wrapper.__wrapped__ = method  # type: ignore
    return memoize_left_rec_wrapper

def ast_dump(node, annotate_fields=True, indent=None, level=0):
    """
    将AST节点转换为字符串表示
    
    Args:
        node: 要转换的AST节点
        annotate_fields: 是否注释字段
        indent: 缩进级别
        level: 当前节点层级
    """
    def is_ast_node(obj):
        return hasattr(obj, '__class__') and hasattr(obj, '__dict__') and isinstance(obj, ASTNode)

    def format_node(node, level):
        pad = ' ' * (indent * level) if indent else ''
        next_pad = ' ' * (indent * (level + 1)) if indent else ''
        cls_name = node.__class__.__name__
        fields = [(k, v) for k, v in node.__dict__.items() if not k.startswith('_')]
        if not fields:
            return f"{cls_name}()"
        
        # 根据indent决定分隔符
        sep = '' if indent is None else '\n'
        
        lines = [f"{cls_name}("]
        for i, (k, v) in enumerate(fields):
            if isinstance(v, list):
                if not v:
                    value_str = '[]'
                else:
                    list_sep = ', ' if indent is None else ',\n'
                    list_pad = '' if indent is None else next_pad + (' ' * indent)
                    value_str = list_sep.join(
                        list_pad + (format_node(item, level + 2) if is_ast_node(item) else repr(item))
                        for item in v
                    )
                    if indent is not None:
                        value_str = '[\n' + value_str + f'\n{next_pad}]'
                    else:
                        value_str = '[' + value_str + ']'
            elif isinstance(v, dict):
                if not v:
                    value_str = '{}'
                else:
                    list_sep = ', ' if indent is None else ',\n'
                    list_pad = '' if indent is None else next_pad + (' ' * indent)
                    value_str = list_sep.join(
                        list_pad + (format_node(key, level + 2) if is_ast_node(key) else repr(key)) + ': ' + (format_node(val, level + 2) if is_ast_node(val) else repr(val))
                        for key, val in v.items()
                    )
                    if indent is not None:
                        value_str = '{\n' + value_str + f'\n{next_pad}' + '}'
                    else:
                        value_str = '{' + value_str + '}'
            elif is_ast_node(v):
                value_str = format_node(v, level + 1)
            else:
                value_str = repr(v)
                
            if annotate_fields:
                lines.append(f"{next_pad}{k}={value_str},")
            else:
                lines.append(f"{next_pad}{value_str},")
                
        lines[-1] = lines[-1].rstrip(',')
        lines.append(f"{pad})")
        return sep.join(lines)
    return format_node(node, level)
    

class Parser:
    """Parsing base class."""

    def __init__(self, tokenizer: Tokenizer):
        self._tokenizer = tokenizer
        self._level = 0
        self._cache: Dict[Tuple[Mark, str, Tuple[Any, ...]], Tuple[Any, Mark]] = {}

        # Integer tracking wether we are in a left recursive rule or not. Can be useful
        # for error reporting.
        self.in_recursive_rule = 0

        # Pass through common tokenizer methods.
        self._mark = self._tokenizer.mark
        self._reset = self._tokenizer.reset

        # Are we looking for syntax error ? When true enable matching on invalid rules
        self.call_invalid_rules = False

    @abstractmethod
    def start(self) -> Any:
        """Expected grammar entry point.

        This is not strictly necessary but is assumed to exist in most utility
        functions consuming parser instances.

        """
        pass

    def showpeek(self) -> str:
        tok = self._tokenizer.peek()
        return tok.__repr__()

    @memoize
    def name(self) -> Token | None:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NAME and not tok.is_keyword:
            return self._tokenizer.getnext()
        return None

    @memoize
    def number(self) -> Token | None:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NUMBER:
            return self._tokenizer.getnext()
        return None

    @memoize
    def string(self) -> Token | None:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.STRING:
            return self._tokenizer.getnext()
        return None

    @memoize
    def include_header(self) -> Token | None:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.INCLUDE_HEADER:
            return self._tokenizer.getnext()
        return None

    @memoize
    def op(self) -> Token | None:
        # TODO 需要考虑实现方式
        tok = self._tokenizer.peek()
        if tok.type in [
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.STAR,
            TokenType.SLASH,
            TokenType.PERCENT,
            TokenType.EQUAL,
            TokenType.ASSIGN,
        ]:
            return self._tokenizer.getnext()
        return None

    @memoize
    def type_comment(self) -> Token | None:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.COMMENT:
            return self._tokenizer.getnext()
        return None

    @memoize
    def soft_keyword(self) -> Token | None:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NAME and tok.is_keyword:
            return self._tokenizer.getnext()
        return None

    @memoize
    def expect(self, type: str) -> Token | None:
        # TODO 此处逻辑需要进一步检查
        tok = self._tokenizer.peek()
        if tok and tok.string == type:
            return self._tokenizer.getnext()
        return None

    def expect_forced(self, res: Any, expectation: str) -> Token:
        if res is None:
            raise self.make_syntax_error(f"expected {expectation}")
        return res

    def positive_lookahead(self, func: Callable[..., T], *args: object) -> T:
        mark = self._mark()
        ok = func(*args)
        self._reset(mark)
        return ok

    def negative_lookahead(self, func: Callable[..., object], *args: object) -> bool:
        mark = self._mark()
        ok = func(*args)
        self._reset(mark)
        return not ok

    def make_syntax_error(self, message: str, filename: str = "<unknown>") -> SyntaxError:
        tok = self._tokenizer.diagnose()
        return SyntaxError(f"{message} at {filename}:col {tok.column} line {tok.line}")
