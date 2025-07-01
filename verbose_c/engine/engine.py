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
    processed_code: str | None = None
    lineno_table: list[tuple[int, int]] | None = None


def generate_parser(grammar_path: str, output_path: str, log_path: str | None = None):
    """
    根据语法文件生成解析器，并可选择性地记录日志。

    Args:
        grammar_path (str): 语法文件的路径 (.gram)。
        output_path (str): 生成的解析器文件路径 (.py)。
        log_path (str, optional): 解析器生成日志的输出路径。
    """
    print(f"从 {grammar_path} 生成解析器到 {output_path}...")
    t0 = time.time()
    grammar, parser, tokenizer, gen = build_python_parser_and_generator(
        grammar_path,
        output_path
    )
    t1 = time.time()
    
    validate_grammar(grammar)
    
    if log_path:
        if os.path.exists(log_path):
            os.remove(log_path)

        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Verbose-C 语法分析器生成日志\n")
            f.write(f"# 源文件: {grammar_path}\n")
            f.write("# 生成时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
            
            f.write("\n=== 原始语法结构 ===\n")
            for line in repr(grammar).splitlines():
                f.write("    " + line + "\n")
                
            f.write("\n=== 干净语法代码 ===\n")
            for line in str(grammar).splitlines():
                f.write("    " + line + "\n")
            
            f.write("\n=== 首项图 ===\n")
            for src, dsts in gen.first_graph.items():
                f.write(f"    {src} -> {', '.join(dsts)}\n")
            
            f.write("\n=== 首项强连通分量 ===\n")
            for scc in gen.first_sccs:
                f.write("    " + str(scc))
                if len(scc) > 1:
                    f.write(
                        f"    # 间接左递归; 领导者: {', '.join(name for name in scc if grammar.rules[name].leader)}\n"
                    )
                else:
                    name = next(iter(scc))
                    if name in gen.first_graph[name]:
                        f.write("    # 左递归\n")
                    else:
                        f.write("\n")
            
            dt = t1 - t0
            diag = tokenizer.diagnose()
            nlines = diag.end[0]
            f.write(f"\n\n总耗时: {dt:.3f} 秒; 共 {nlines} 行")
            if dt:
                f.write(f"; {nlines / dt:.0f} 行/s\n")
            else:
                f.write("\n")
            f.write("缓存大小:\n")
            f.write(f"    token array : {len(tokenizer._tokens):10}\n")
            f.write(f"        cache : {len(parser._cache):10}\n")
            
        print(f"解析器生成日志已输出到 {log_path}")


def compile_module(
    file_path: str, 
    refresh_parser: bool = False,
    need_tokens: bool = False,
    need_ast: bool = False,
    need_processed_code: bool = False,
    log_parser_gen_path: str | None = None
) -> CompilerOutput:
    """
    编译单个模块文件，返回编译结果。

    Args:
        file_path (str): 要编译的源文件路径。
        refresh_parser (bool): 是否强制重新生成解析器。
        log_parser_gen_path (str, optional): 解析器生成日志的输出路径。

    Returns:
        CompilerOutput: 包含字节码等编译结果的对象。
    """
    if refresh_parser or not os.path.exists(default_parser_output):
        generate_parser(grammar_file, default_parser_output, log_parser_gen_path)

    spec = importlib.util.spec_from_file_location("parser", default_parser_output)
    parser_module = importlib.util.module_from_spec(spec)
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
        processed_code=processed_code if need_processed_code else None,
        lineno_table=opcode_gen.lineno_table
    )
