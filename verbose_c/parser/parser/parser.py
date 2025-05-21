import argparse
import ast
import sys
import time
import traceback
from abc import abstractmethod
from typing import Any, Callable, ClassVar, Dict, Optional, Tuple, Type, TypeVar, cast

from verbose_c.parser.parser.ast.node import ASTNode
from verbose_c.parser.tokenizer.enum import TokenType
from verbose_c.parser.tokenizer.tokenizer import Mark, Tokenizer
from verbose_c.parser.tokenizer.token import Token

T = TypeVar("T")
P = TypeVar("P", bound="Parser")
F = TypeVar("F", bound=Callable[..., Any])


def logger(method: F) -> F:
    """For non-memoized functions that we want to be logged.

    (In practice this is only non-leader left-recursive functions.)
    """
    method_name = method.__name__

    def logger_wrapper(self: P, *args: object) -> F:
        if not self._verbose:
            return method(self, *args)
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
        # Fast path: cache hit, and not verbose.
        if key in self._cache and not self._verbose:
            tree, endmark = self._cache[key]
            self._reset(endmark)
            return tree
        # Slow path: no cache hit, or verbose.
        verbose = self._verbose
        argsr = ",".join(repr(arg) for arg in args)
        fill = "  " * self._level
        if key not in self._cache:
            if verbose:
                print(f"{fill}{method_name}({argsr}) ... (looking at {self.showpeek()})")
            self._level += 1
            tree = method(self, *args)
            self._level -= 1
            if verbose:
                print(f"{fill}... {method_name}({argsr}) -> {tree!s:.200}")
            endmark = self._mark()
            self._cache[key] = tree, endmark
        else:
            tree, endmark = self._cache[key]
            if verbose:
                print(f"{fill}{method_name}({argsr}) -> {tree!s:.200}")
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
        # Fast path: cache hit, and not verbose.
        if key in self._cache and not self._verbose:
            tree, endmark = self._cache[key]
            self._reset(endmark)
            return tree
        # Slow path: no cache hit, or verbose.
        verbose = self._verbose
        fill = "  " * self._level
        if key not in self._cache:
            if verbose:
                print(f"{fill}{method_name} ... (looking at {self.showpeek()})")
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
            if verbose:
                print(f"{fill}Recursive {method_name} at {mark} depth {depth}")

            while True:
                self._reset(mark)
                self.in_recursive_rule += 1
                try:
                    result = method(self)
                finally:
                    self.in_recursive_rule -= 1
                endmark = self._mark()
                depth += 1
                if verbose:
                    print(
                        f"{fill}Recursive {method_name} at {mark} depth {depth}: {result!s:.200} to {endmark}"
                    )
                if not result:
                    if verbose:
                        print(f"{fill}Fail with {lastresult!s:.200} to {lastmark}")
                    break
                if endmark <= lastmark:
                    if verbose:
                        print(f"{fill}Bailing with {lastresult!s:.200} to {lastmark}")
                    break
                self._cache[key] = lastresult, lastmark = result, endmark

            self._reset(lastmark)
            tree = lastresult

            self._level -= 1
            if verbose:
                print(f"{fill}{method_name}() -> {tree!s:.200} [cached]")
            if tree:
                endmark = self._mark()
            else:
                endmark = mark
                self._reset(endmark)
            self._cache[key] = tree, endmark
        else:
            tree, endmark = self._cache[key]
            if verbose:
                print(f"{fill}{method_name}() -> {tree!s:.200} [fresh]")
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
                    value_str = list_sep.join(
                        list_pad + (format_node(k, level + 2) if is_ast_node(k) else repr(k)) + ': ' + (format_node(v, level + 2) if is_ast_node(v) else repr(v))
                        for k, v in v.items()
                    )
                    if indent is not None:
                        value_str = '{\n' + value_str + f'\n{next_pad}'+ '}'
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

    def __init__(self, tokenizer: Tokenizer, *, verbose: bool = False):
        self._tokenizer = tokenizer
        self._verbose = verbose
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
    def name(self) -> Token:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NAME:
            return self._tokenizer.getnext()
        return None

    @memoize
    def number(self) -> Token:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NUMBER:
            return self._tokenizer.getnext()
        return None

    @memoize
    def string(self) -> Token:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.STRING:
            return self._tokenizer.getnext()
        return None

    @memoize
    def op(self) -> Token:
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
    def type_comment(self) -> Token:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.COMMENT:
            return self._tokenizer.getnext()
        return None

    @memoize
    def soft_keyword(self) -> Token:
        tok = self._tokenizer.peek()
        if tok.type == TokenType.NAME and tok.is_keyword:
            return self._tokenizer.getnext()
        return None

    @memoize
    def expect(self, type: str) -> Token:
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


def simple_parser_main(parser_class: Type[Parser]) -> None:
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Print timing stats; repeat for more debug output",
    )
    argparser.add_argument(
        "-q", "--quiet", action="store_true", help="Don't print the parsed program"
    )
    argparser.add_argument("-r", "--run", action="store_true", help="Run the parsed program")
    argparser.add_argument("filename", help="Input file ('-' to use stdin)")

    args = argparser.parse_args()
    verbose = args.verbose
    verbose_tokenizer = verbose >= 3
    verbose_parser = verbose == 2 or verbose >= 4

    t0 = time.time()

    filename = args.filename
    if filename == "" or filename == "-":
        filename = "<stdin>"
        file = sys.stdin
    else:
        file = open(args.filename)
    try:
        tokenizer = Tokenizer(filename, file.read(), verbose=verbose_tokenizer)
        parser = parser_class(tokenizer, verbose=verbose_parser)
        tree = parser.start()
        try:
            if file.isatty():
                endpos = 0
            else:
                endpos = file.tell()
        except IOError:
            endpos = 0
    finally:
        if file is not sys.stdin:
            file.close()

    t1 = time.time()

    if not tree:
        err = parser.make_syntax_error(filename)
        traceback.print_exception(err.__class__, err, None)
        sys.exit(1)

    if not args.quiet:
        print(ast_dump(tree, indent=4))
    if args.run:
        exec(compile(tree, filename=filename, mode="exec"))

    if verbose:
        dt = t1 - t0
        diag = tokenizer.diagnose()
        nlines = diag.line
        if diag.type == TokenType.END:
            nlines -= 1
        print(f"Total time: {dt:.3f} sec; {nlines} lines", end="")
        if endpos:
            print(f" ({endpos} bytes)", end="")
        if dt:
            print(f"; {nlines / dt:.0f} lines/sec")
        else:
            print()
        print("Caches sizes:")
        print(f"  token array : {len(tokenizer.tokens):10}")
        print(f"        cache : {len(parser._cache):10}")
        ## print_memstats()
