import os
import importlib.util
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

from verbose_c.fs.source_manager import SourceManager
from verbose_c.preprocessor.preprocessor import Preprocessor
from verbose_c.parser.lexer.tokenizer import Tokenizer
from verbose_c.parser.lexer.token import Token
from verbose_c.parser.parser.ast.node import ASTNode
from verbose_c.compiler.compiler import Compiler
from verbose_c.parser.ppg.build import build_python_parser_and_generator
from verbose_c.parser.ppg.validator import validate_grammar
from verbose_c.error import VBCCompileError, VBCRuntimeError
from verbose_c.fs.artifact_store import ArtifactStore
from verbose_c.fs.incremental_compile import IncrementalCompiler
from verbose_c.engine.recorder import PipelineRecorder, create_dump_path

default_parser_output = "parser.py"
grammar_file = "Grammar/verbose_c.gram"


@dataclass
class ParserGenerationReport:
    """用于封装解析器生成过程的结构化信息。"""
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
    """用于封装单次编译结果的数据类。"""
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
    optimization_result: Any | None = None
    dependencies: list[str] = field(default_factory=list)


@dataclass
class CompileContext:
    """编译流水线各阶段中间产物，失败时保留已完成阶段的数据。"""
    processed_code: str = ""
    tokens: list[Token] | None = None
    ast_node: ASTNode | None = None
    parser_generation_report: ParserGenerationReport | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """单次编译/运行流程的结果。"""
    success: bool
    exit_code: int = 0
    dump_path: str | None = None
    artifact_path: str | None = None
    compilation_output: CompilerOutput | None = None
    warnings: list[str] = field(default_factory=list)
    error: Exception | None = None


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
    """根据语法文件生成解析器，并返回生成报告。"""
    t0 = time.time()
    grammar, parser, tokenizer, gen = build_python_parser_and_generator(
        grammar_path,
        output_path
    )
    t1 = time.time()

    validate_grammar(grammar)
    return _build_parser_generation_report(
        grammar_path,
        output_path,
        grammar,
        parser,
        tokenizer,
        gen,
        t1 - t0
    )


def ensure_parser(refresh_parser: bool = False) -> ParserGenerationReport | None:
    """若 parser.py 不存在或需要刷新，则生成解析器并返回报告。"""
    if refresh_parser or not os.path.exists(default_parser_output):
        return generate_parser(grammar_file, default_parser_output)
    return None


def _load_parser_module():
    spec = importlib.util.spec_from_file_location("parser", default_parser_output)
    if spec is None:
        raise ImportError(f"无法加载解析器模块: {default_parser_output}")

    parser_module = importlib.util.module_from_spec(spec)
    if spec.loader is None or parser_module is None:
        raise ImportError(f"无法加载解析器模块: {default_parser_output}")

    spec.loader.exec_module(parser_module)
    return parser_module


def compile_module(
    file_path: str,
    refresh_parser: bool = False,
    recorder: PipelineRecorder | None = None,
    optimize_level: int = 0,
) -> CompilerOutput:
    """
    编译单个模块文件，分阶段执行并在每阶段完成后通知 recorder。

    Args:
        file_path (str): 要编译的源文件路径。
        refresh_parser (bool): 是否强制重新生成解析器。
        recorder (PipelineRecorder | None): 输出记录器。
    """
    context = CompileContext()

    report = ensure_parser(refresh_parser)
    if report is not None:
        context.parser_generation_report = report
        if recorder:
            recorder.on_parser_generated(report)

    parser_module = _load_parser_module()

    file_path = os.path.abspath(file_path)

    source_manager = SourceManager()
    
    # 词法分析
    tokenizer = Tokenizer(file_path, source_manager)
    raw_tokens = tokenizer.tokens
    context.tokens = raw_tokens
    if recorder:
        recorder.on_raw_tokens(raw_tokens)

    preprocessor = Preprocessor(source_manager)
    processed_tokens = preprocessor.process_tokens(raw_tokens)
    tokenizer.tokens = processed_tokens
    tokenizer._total_tokens = len(processed_tokens)
    tokenizer._index = 0
    context.tokens = processed_tokens
    if recorder:
        recorder.on_preprocessed_tokens(processed_tokens)

    # 语法分析
    parser = parser_module.GeneratedParser(tokenizer)
    ast_node = parser.start()
    if ast_node is None:
        error_report = parser.get_error_report() if parser.has_errors() else "未知的解析错误"
        raise VBCCompileError(f"在文件 {file_path} 中解析失败:\n{error_report}", filepath=file_path)

    context.ast_node = ast_node
    if recorder:
        recorder.on_ast(ast_node)

    compiler = Compiler(ast_node, source_path=file_path, optimize_level=optimize_level)
    compiler.compile()
    opcode_gen = compiler.opcode_generator
    context.warnings = compiler.warnings

    output = CompilerOutput(
        bytecode=compiler.bytecode,
        constant_pool=compiler.constant_pool,
        function_compilation_results=opcode_gen.function_compilation_results,
        labels=opcode_gen.labels,
        tokens=tokenizer.tokens,
        ast_node=ast_node,
        processed_code="",
        lineno_table=opcode_gen.lineno_table,
        warnings=compiler.warnings,
        parser_generation_report=context.parser_generation_report,
        optimization_result=opcode_gen.optimization_result,
        dependencies=sorted(preprocessor.dependencies),
    )
    if recorder:
        recorder.on_compiled(output)
    return output


def _load_bytecode_compilation_output(filename: str) -> tuple[CompilerOutput, str]:
    """加载 .vbb 并恢复为运行所需的编译输出结构。"""
    artifact_store = ArtifactStore()
    bytecode, metadata = artifact_store.load_bytecode(filename)
    constant_pool = metadata.get("constant_pool", [])
    lineno_table = metadata.get("lineno_table", [])
    source_path = metadata.get("source_path") or filename
    compilation_output = CompilerOutput(
        bytecode=bytecode,
        constant_pool=constant_pool,
        function_compilation_results=metadata.get("function_compilation_results", {}),
        labels=metadata.get("labels", {}),
        lineno_table=lineno_table,
    )
    return compilation_output, source_path


def _execute_compilation_output(
    compilation_output: CompilerOutput,
    source_path: str,
    recorder: PipelineRecorder,
) -> tuple[int, Any]:
    """执行已恢复或刚生成的字节码。"""
    from verbose_c.vm.core import VBCVirtualMachine

    vm = VBCVirtualMachine(debug_log_collector=recorder.create_vm_log_collector())
    exit_code = vm.excute(
        bytecode=compilation_output.bytecode,
        constants=compilation_output.constant_pool,
        source_path=source_path,
        lineno_table=compilation_output.lineno_table,
        source_code=_read_source_lines(source_path),
    )
    return exit_code, vm


def run_parser_generation(
    *,
    log_modules: set[str],
    dump_modules: set[str],
    dump_path: str | None = None,
) -> RunResult:
    """编译语法文件生成解析器。"""
    if dump_path is None and dump_modules:
        dump_path = create_dump_path(grammar_file)

    recorder = PipelineRecorder(
        source_filename=grammar_file,
        log_modules=log_modules,
        dump_modules=dump_modules,
        dump_path=dump_path,
        dump_title="Verbose-C Parser Dump",
        basic_info_lines=[
            f"- 源语法文件: `{grammar_file}`",
            f"- 输出解析器: `{default_parser_output}`",
        ],
    )

    report = None
    captured_error = None
    try:
        report = generate_parser(grammar_file, default_parser_output)
        recorder.on_parser_generated(report)
    except Exception as e:
        captured_error = e
        print(f"编译语法文件时发生错误: {e}")
        traceback.print_exc()
        recorder.on_error(e)
    finally:
        final_path = recorder.finalize(success=captured_error is None)

    return RunResult(
        success=captured_error is None,
        dump_path=final_path,
        error=captured_error,
    )


def run_source_file(
    filename: str,
    *,
    log_modules: set[str],
    dump_modules: set[str],
    dump_path: str | None = None,
    output_path: str | None = None,
    execute: bool = True,
    refresh_parser: bool = False,
    show_warnings: bool = True,
    optimize_level: int = 0,
) -> RunResult:
    """编译并可选执行单个源文件，由 recorder 负责 log 与 dump 输出。"""
    if dump_path is None and dump_modules:
        dump_path = create_dump_path(filename)

    recorder = PipelineRecorder(
        source_filename=filename,
        log_modules=log_modules,
        dump_modules=dump_modules,
        dump_path=dump_path,
    )

    compilation_result = None
    captured_error = None
    compile_warnings: list[str] = []
    exit_code = 0
    vm = None
    artifact_store = ArtifactStore()
    incremental_compiler = IncrementalCompiler(artifact_store)
    artifact_path = output_path or artifact_store.artifact_path_for_source(filename)

    recorder.log_compile_start()
    try:
        needs_recompile = incremental_compiler.needs_recompile(
            filename,
            artifact_path=artifact_path,
            optimize_level=optimize_level,
            refresh_parser=refresh_parser,
        )
        if needs_recompile:
            recorder.log_compile_engine()
            compilation_result = compile_module(
                file_path=filename,
                refresh_parser=refresh_parser,
                recorder=recorder,
                optimize_level=optimize_level,
            )
            compile_warnings = compilation_result.warnings or []
            if show_warnings and compile_warnings:
                for warning_line in compile_warnings:
                    print(f"警告: {warning_line}")

            artifact_store.save_bytecode(
                artifact_path,
                compilation_result.bytecode,
                metadata={
                    "constant_pool": compilation_result.constant_pool,
                    "lineno_table": compilation_result.lineno_table,
                    "source_path": os.path.abspath(filename),
                    "labels": compilation_result.labels,
                    "function_compilation_results": compilation_result.function_compilation_results,
                },
            )
            incremental_compiler.write_manifest(
                filename,
                compilation_result.dependencies,
                artifact_path=artifact_path,
                optimize_level=optimize_level,
                refresh_parser=refresh_parser,
            )
            recorder.log_compile_done()
            source_path = filename
        else:
            compilation_result, source_path = _load_bytecode_compilation_output(artifact_path)
            recorder.on_compiled(compilation_result)

        if execute:
            recorder.log_vm_start()
            exit_code, vm = _execute_compilation_output(
                compilation_result,
                source_path=source_path,
                recorder=recorder,
            )
            recorder.log_vm_done()

    except VBCRuntimeError as e:
        captured_error = e
        exit_code = 1
        recorder.on_error(e)
    except VBCCompileError as e:
        captured_error = e
        exit_code = 1
        print(f"编译错误: 文件 {e.filepath}")
        for error_line in e.message.split('\n'):
            print(f"    {error_line}")
        compile_warnings = e.warnings or []
        if show_warnings and compile_warnings:
            for warning_line in compile_warnings:
                print(f"警告: {warning_line}")
        recorder.on_error(e)
    except Exception as e:
        captured_error = e
        exit_code = 1
        print(f"发生了一个意外的内部错误: {e}")
        traceback.print_exc()
        recorder.on_error(e)
    finally:
        if vm is not None:
            recorder.on_memory(vm.memory)
        final_path = recorder.finalize(success=captured_error is None)

    return RunResult(
        success=captured_error is None,
        exit_code=exit_code,
        dump_path=final_path,
        artifact_path=artifact_path,
        compilation_output=compilation_result,
        warnings=compile_warnings,
        error=captured_error,
    )


def run_bytecode_file(
    filename: str,
    *,
    log_modules: set[str],
    dump_modules: set[str],
    dump_path: str | None = None,
) -> RunResult:
    """加载并执行字节码产物。"""
    if dump_path is None and dump_modules:
        dump_path = create_dump_path(filename)

    recorder = PipelineRecorder(
        source_filename=filename,
        log_modules=log_modules,
        dump_modules=dump_modules,
        dump_path=dump_path,
    )

    captured_error = None
    exit_code = 0
    vm = None
    compilation_output = None
    artifact_store = ArtifactStore()

    try:
        bytecode, metadata = artifact_store.load_bytecode(filename)
        constant_pool = metadata.get("constant_pool", [])
        lineno_table = metadata.get("lineno_table", [])
        source_path = metadata.get("source_path") or filename
        compilation_output = CompilerOutput(
            bytecode=bytecode,
            constant_pool=constant_pool,
            function_compilation_results=metadata.get("function_compilation_results", {}),
            labels=metadata.get("labels", {}),
            lineno_table=lineno_table,
        )
        recorder.on_compiled(compilation_output)

        recorder.log_vm_start()
        from verbose_c.vm.core import VBCVirtualMachine

        vm = VBCVirtualMachine(debug_log_collector=recorder.create_vm_log_collector())
        exit_code = vm.excute(
            bytecode=bytecode,
            constants=constant_pool,
            source_path=source_path,
            lineno_table=lineno_table,
            source_code=_read_source_lines(source_path),
        )
        recorder.log_vm_done()

    except VBCRuntimeError as e:
        captured_error = e
        exit_code = 1
        recorder.on_error(e)
    except VBCCompileError as e:
        captured_error = e
        exit_code = 1
        print(f"编译错误: 文件 {e.filepath}")
        for error_line in e.message.split('\n'):
            print(f"    {error_line}")
        recorder.on_error(e)
    except Exception as e:
        captured_error = e
        exit_code = 1
        print(f"发生了一个意外的内部错误: {e}")
        traceback.print_exc()
        recorder.on_error(e)
    finally:
        if vm is not None:
            recorder.on_memory(vm.memory)
        final_path = recorder.finalize(success=captured_error is None)

    return RunResult(
        success=captured_error is None,
        exit_code=exit_code,
        dump_path=final_path,
        artifact_path=os.path.abspath(filename),
        compilation_output=compilation_output,
        error=captured_error,
    )


def _read_source_lines(source_path: str | None) -> list[str]:
    """读取源码行用于运行时错误上下文。"""
    if not source_path or not os.path.exists(source_path):
        return []
    try:
        with open(source_path, "r", encoding="utf-8") as file:
            return file.read().split("\n")
    except OSError:
        return []
