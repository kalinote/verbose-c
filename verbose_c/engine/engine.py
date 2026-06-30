import os
import importlib.util
import time
from dataclasses import dataclass, field
from typing import Any

from verbose_c.preprocessor.preprocessor import Preprocessor
from verbose_c.parser.lexer.tokenizer import Tokenizer
from verbose_c.parser.lexer.token import Token
from verbose_c.parser.parser.ast.node import ASTNode
from verbose_c.compiler.compiler import Compiler
from verbose_c.parser.ppg.build import build_python_parser_and_generator
from verbose_c.parser.ppg.validator import validate_grammar

default_parser_output = "parser.py"
grammar_file = "Grammar/verbose_c.gram"


@dataclass
class ParserGenerationReport:
    """
    用于封装解析器生成过程的结构化信息。
    """
    grammar_path: str
    output_path: str
    generated_at: str
    duration_seconds: float
    line_count: int
    token_count: int
    parser_cache_size: int
    raw_grammar: str
    clean_grammar: str
    first_graph: dict[str, list[str]]
    first_sccs: list[dict[str, str]]


@dataclass
class CompilerOutput:
    """
    用于封装单次编译结果的数据类。
    """
    bytecode: list[tuple[Any, ...]]
    constant_pool: list[Any]
    function_compilation_results: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)
    tokens: list[Token] | None = None
    ast_node: ASTNode | None = None
    processed_code: str = ""
    lineno_table: list[tuple[int, int]] | None = None
    warnings: list[str] = field(default_factory=list)
    parser_generation_report: ParserGenerationReport | None = None


def _build_parser_generation_report(
    grammar_path: str,
    output_path: str,
    grammar,
    parser,
    tokenizer,
    gen,
    duration_seconds: float
) -> ParserGenerationReport:
    diag = tokenizer.diagnose()
    first_graph = {src: list(dsts) for src, dsts in gen.first_graph.items()}
    first_sccs = []

    for scc in gen.first_sccs:
        names = sorted(scc)
        status = "普通"
        leaders = []
        if len(scc) > 1:
            status = "间接左递归"
            leaders = [name for name in names if grammar.rules[name].leader]
        else:
            name = names[0]
            if name in gen.first_graph[name]:
                status = "左递归"

        first_sccs.append({
            "rules": ", ".join(names),
            "status": status,
            "leaders": ", ".join(leaders) if leaders else "-"
        })

    return ParserGenerationReport(
        grammar_path=grammar_path,
        output_path=output_path,
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        duration_seconds=duration_seconds,
        line_count=diag.end[0],
        token_count=len(tokenizer._tokens),
        parser_cache_size=len(parser._cache),
        raw_grammar=repr(grammar),
        clean_grammar=str(grammar),
        first_graph=first_graph,
        first_sccs=first_sccs
    )


def generate_parser(grammar_path: str, output_path: str) -> ParserGenerationReport:
    """
    根据语法文件生成解析器，并返回生成报告。

    Args:
        grammar_path (str): 语法文件的路径 (.gram)。
        output_path (str): 生成的解析器文件路径 (.py)。
    """
    t0 = time.time()
    grammar, parser, tokenizer, gen = build_python_parser_and_generator(
        grammar_path,
        output_path
    )
    t1 = time.time()
    
    validate_grammar(grammar)
    report = _build_parser_generation_report(
        grammar_path,
        output_path,
        grammar,
        parser,
        tokenizer,
        gen,
        t1 - t0
    )
    return report


def compile_module(
    file_path: str, 
    refresh_parser: bool = False,
    need_tokens: bool = False,
    need_ast: bool = False,
    need_processed_code: bool = False
) -> CompilerOutput:
    """
    编译单个模块文件，返回编译结果。

    Args:
        file_path (str): 要编译的源文件路径。
        refresh_parser (bool): 是否强制重新生成解析器。
    Returns:
        CompilerOutput: 包含字节码等编译结果的对象。
    """
    parser_generation_report = None
    if refresh_parser or not os.path.exists(default_parser_output):
        parser_generation_report = generate_parser(grammar_file, default_parser_output)

    spec = importlib.util.spec_from_file_location("parser", default_parser_output)
    
    if spec is None:
        raise ImportError(f"无法加载解析器模块: {default_parser_output}")
    
    parser_module = importlib.util.module_from_spec(spec)
    
    if spec.loader is None or parser_module is None:
        raise ImportError(f"无法加载解析器模块: {default_parser_output}")
    
    spec.loader.exec_module(parser_module)

    # 预处理源代码
    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    
    preprocessor = Preprocessor()
    processed_code = preprocessor.process(source_code, file_path)

    # 词法分析和语法分析
    tokenizer = Tokenizer(file_path, processed_code)
    parser = parser_module.GeneratedParser(tokenizer)
    ast_node = parser.start()

    if ast_node is None:
        error_report = parser.get_error_report() if parser.has_errors() else "未知的解析错误"
        raise SyntaxError(f"在文件 {file_path} 中解析失败:\n{error_report}")

    # 编译AST
    compiler = Compiler(ast_node, source_path=file_path)
    compiler.compile()
    
    opcode_gen = compiler.opcode_generator

    return CompilerOutput(
        bytecode=compiler.bytecode,
        constant_pool=compiler.constant_pool,
        function_compilation_results=opcode_gen.function_compilation_results,
        labels=opcode_gen.labels,
        tokens=tokenizer.tokens if need_tokens else None,
        ast_node=ast_node if need_ast else None,
        processed_code=processed_code if need_processed_code else source_code,
        lineno_table=opcode_gen.lineno_table,
        warnings=compiler.warnings,
        parser_generation_report=parser_generation_report
    )
