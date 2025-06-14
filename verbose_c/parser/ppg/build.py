import pathlib
import tokenize

from verbose_c.parser.ppg.grammar import Grammar
from verbose_c.parser.ppg.grammar_parser import GeneratedParser as GrammarParser
from verbose_c.parser.ppg.parser import Parser
from verbose_c.parser.ppg.parser_generator import ParserGenerator
from verbose_c.parser.ppg.python_generator import PythonParserGenerator
from verbose_c.parser.ppg.tokenizer import Tokenizer

MOD_DIR = pathlib.Path(__file__).resolve().parent

TokenDefinitions = tuple[dict[int, str], dict[str, int], set[str]]


def build_parser(
    grammar_file: str
) -> tuple[Grammar, Parser, Tokenizer]:
    with open(grammar_file, encoding="utf-8") as file:
        tokenizer = Tokenizer(tokenize.generate_tokens(file.readline))
        parser = GrammarParser(tokenizer)
        grammar = parser.start()

        if not grammar:
            raise parser.make_syntax_error(grammar_file)

    return grammar, parser, tokenizer


def build_python_generator(
    grammar: Grammar,
    grammar_file: str,
    output_file: str
) -> ParserGenerator:
    with open(output_file, "w", encoding="utf-8") as file:
        gen: ParserGenerator = PythonParserGenerator(grammar, file)
        gen.generate(grammar_file)
    return gen


def build_python_parser_and_generator(
    grammar_file: str,
    output_file: str
) -> tuple[Grammar, Parser, Tokenizer, ParserGenerator]:
    """为给定的语法生成规则、Python解析器、分词器和解析器生成器

    参数:
        grammar_file (string): 语法文件的路径
        output_file (string): 输出文件的路径
    """
    grammar, parser, tokenizer = build_parser(grammar_file)
    gen = build_python_generator(
        grammar,
        grammar_file,
        output_file,
    )
    return grammar, parser, tokenizer, gen
