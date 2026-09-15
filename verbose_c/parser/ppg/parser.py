import argparse
import ast
import sys
import time
import traceback
from abc import abstractmethod
from typing import Any, Callable, ClassVar, Optional, Type, TypeVar, cast

from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.token import Token
from verbose_c.parser.lexer.tokenizer import Mark, Tokenizer

T = TypeVar("T")
P = TypeVar("P", bound="Parser")
F = TypeVar("F", bound=Callable[..., Any])


def logger(method: F) -> F:
    """For non-memoized functions that we want to be logged.

    (In practice this is only non-leader left-recursive functions.)
    """
    method_name = method.__name__

    def logger_wrapper(self: "Parser", *args: object) -> F:
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

    def memoize_wrapper(self: "Parser", *args: object) -> F:
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

        fill = "  " * self._level
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


class Parser:
    """Parsing base class."""

    KEYWORDS: ClassVar[tuple[str, ...]]

    SOFT_KEYWORDS: ClassVar[tuple[str, ...]]

    def __init__(self, tokenizer: Tokenizer):
        self._tokenizer = tokenizer
        self._level = 0
        self._cache: dict[tuple[Mark, str, tuple[Any, ...]], tuple[Any, Mark]] = {}

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
        return f"{tok.line}.{tok.column}: {tok.type.name}:{tok.string!r}"

    @memoize
    def name(self) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NAME and tok.string not in self.KEYWORDS:
            return self._tokenizer.getnext()
        return None

    @memoize
    def number(self) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NUMBER:
            return self._tokenizer.getnext()
        return None

    @memoize
    def string(self) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.STRING:
            return self._tokenizer.getnext()
        return None

    @memoize
    def op(self) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.OP:
            return self._tokenizer.getnext()
        return None

    @memoize
    def type_comment(self) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.COMMENT:
            return self._tokenizer.getnext()
        return None

    @memoize
    def soft_keyword(self) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NAME and tok.string in self.SOFT_KEYWORDS:
            return self._tokenizer.getnext()
        return None

    @memoize
    def expect(self, type: str) -> Optional[Token]:
        tok = self._tokenizer.peek()
        if tok.string == type or tok.type == TokenType.__members__.get(type):
            return self._tokenizer.getnext()
        return None

    def expect_forced(self, res: Any, expectation: str) -> Optional[Token]:
        if res is None:
            raise self.make_syntax_error(f"期望 {expectation}")
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
        path = tok.path if filename == "<unknown>" else filename
        line = self._tokenizer.get_line_source(path, tok.line)
        return SyntaxError(message, (path, tok.line, 1 + tok.column, line))
