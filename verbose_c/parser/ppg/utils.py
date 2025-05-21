import importlib.util
import io
import sys
import textwrap
import tokenize
from typing import IO, Any, Dict, Final, Optional, Type, cast

from verbose_c.parser.ppg.grammar import Grammar
from verbose_c.parser.ppg.grammar_parser import GeneratedParser as GrammarParser
from verbose_c.parser.ppg.parser import Parser
from verbose_c.parser.ppg.python_generator import PythonParserGenerator
from verbose_c.parser.ppg.tokenizer import Tokenizer


def import_file(full_name: str, path: str) -> Any:
    """Import a python module from a path"""

    spec = importlib.util.spec_from_file_location(full_name, path)
    assert spec
    mod = importlib.util.module_from_spec(spec)

    # We assume this is not None and has an exec_module() method.
    # See https://docs.python.org/3/reference/import.html?highlight=exec_module#loading
    loader = cast(Any, spec.loader)
    loader.exec_module(mod)
    return mod


def generate_parser(
    grammar: Grammar, parser_path: Optional[str] = None, parser_name: str = "GeneratedParser"
) -> Type[Parser]:
    # Generate a parser.
    out = io.StringIO()
    genr = PythonParserGenerator(grammar, out)
    genr.generate("<string>")

    # Load the generated parser class.
    ns: Dict[str, Any] = {}
    if parser_path:
        with open(parser_path, "w") as f:
            f.write(out.getvalue())
        mod = import_file("py_parser", parser_path)
        return getattr(mod, parser_name)
    else:
        exec(out.getvalue(), ns)
        return ns[parser_name]


def run_parser(file: IO[bytes], parser_class: Type[Parser], *, verbose: bool = False) -> Any:
    # Run a parser on a file (stream).
    tokenizer = Tokenizer(tokenize.generate_tokens(file.readline))  # type: ignore # typeshed issue #3515
    parser = parser_class(tokenizer, verbose=verbose)
    result = parser.start()
    if result is None:
        raise parser.make_syntax_error("invalid syntax")
    return result


def parse_string(
    source: str, parser_class: Type[Parser], *, dedent: bool = True, verbose: bool = False
) -> Any:
    # Run the parser on a string.
    if dedent:
        source = textwrap.dedent(source)
    file = io.StringIO(source)
    return run_parser(file, parser_class, verbose=verbose)  # type: ignore # typeshed issue #3515


def make_parser(source: str) -> Type[Parser]:
    # Combine parse_string() and generate_parser().
    grammar = parse_string(source, GrammarParser)
    return generate_parser(grammar)
