import argparse
import os
import re
import time
import traceback
from verbose_c.engine.engine import compile_module, generate_parser, grammar_file
from verbose_c.error import VBCRuntimeError, VBCCompileError

default_parser_output = "parser.py"


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )

    parser.add_argument("filename", help="需要编译的文件（.vbc源代码文件或.gram语法文件）")
    parser.add_argument("--log", nargs="?", const="all", help="按模块输出命令行日志（模块: compile, vm, parser, all；默认 all）")
    parser.add_argument("--dump", nargs="?", const="all", help="导出执行过程日志，支持模块: parser, preprocess, tokens, ast, opcode, const, label, vm, all；默认 all")
    parser.add_argument("--no-warn", help="静默编译告警输出", action="store_true")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    parser.add_argument("--compile-only", help="只编译不执行源代码", action="store_true")
    parser.add_argument("-rp", "--refresh-parser", help="重新生成解析器", action="store_true")
    return parser.parse_args()


def main():
    """根据参数组织编译流程并分发到解析器/编译执行入口。"""
    args = parse_args()
    log_modules = set()
    dump_modules = set()
    allowed_log_modules = {"compile", "vm", "parser", "all"}
    allowed_dump_modules = {"parser", "preprocess", "tokens", "ast", "opcode", "const", "label", "vm", "all"}

    if args.log is not None:
        log_modules = {module.strip().lower() for module in args.log.split(",") if module.strip()}
        if not log_modules:
            log_modules = {"all"}
        invalid_log = sorted(log_modules - allowed_log_modules)
        if invalid_log:
            print(f"错误: --log 存在不支持的模块: {', '.join(invalid_log)}")
            return

    if args.dump is not None:
        dump_modules = {module.strip().lower() for module in args.dump.split(",") if module.strip()}
        if not dump_modules:
            dump_modules = {"all"}
        invalid_dump = sorted(dump_modules - allowed_dump_modules)
        if invalid_dump:
            print(f"错误: --dump 存在不支持的模块: {', '.join(invalid_dump)}")
            return

    if not args.compile_parser and args.filename and not os.path.exists(args.filename):
        print(f"错误: 文件 '{args.filename}' 不存在")
        return

    if args.compile_parser:
        dump_path = _create_dump_path(grammar_file) if dump_modules else None
        report = None
        captured_error = None
        try:
            log_parser = "all" in log_modules or "parser" in log_modules
            report = generate_parser(
                grammar_file,
                default_parser_output
            )
            if log_parser:
                print(_format_parser_generation_markdown(report, heading_level=2, include_details=False))
        except Exception as e:
            captured_error = e
            print(f"编译语法文件时发生错误: {e}")
            traceback.print_exc()
        finally:
            if dump_path:
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write("# Verbose-C Parser Dump\n\n")
                    toc_lines = ["- [基本信息](#基本信息)"]
                    if captured_error is not None:
                        toc_lines.append("- [错误信息](#错误信息)")
                    if report is not None:
                        toc_lines.append("- [解析器生成](#解析器生成)")
                    _write_dump_toc(f, toc_lines)

                    f.write("## 基本信息\n\n")
                    f.write(f"- 源语法文件: `{grammar_file}`\n")
                    f.write(f"- 输出解析器: `{default_parser_output}`\n")
                    f.write(f"- 生成时间: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n")
                    f.write(f"- 编译结果: `{'失败' if captured_error else '成功'}`\n\n")

                    if captured_error is not None:
                        _write_error_dump_section(f, captured_error)

                    if report is not None:
                        f.write(_format_parser_generation_markdown(report, heading_level=2, include_details=True))

                print(f"\n运行记录已保存到：{dump_path}")
    else:
        dump_path = _create_dump_path(args.filename) if dump_modules else None

        compile_source_file(
            filename=args.filename,
            log_modules=log_modules,
            dump_modules=dump_modules,
            dump_path=dump_path,
            execute=not args.compile_only,
            refresh_parser=args.refresh_parser,
            show_warnings=not args.no_warn
        )


def _create_dump_path(filename):
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', filename)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs("dumps", exist_ok=True)
    return os.path.join("dumps", f"{safe_name}_{timestamp}.md")


def _escape_markdown_table_cell(value):
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")


def _write_dump_toc(file, toc_lines):
    file.write("## 目录\n\n")
    file.write("\n".join(toc_lines))
    file.write("\n\n")


def _write_error_dump_section(file, error):
    file.write("## 错误信息\n\n")
    file.write("```text\n")
    file.write(f"{type(error).__name__}: {error}\n")
    file.write("```\n\n")


def _format_parser_generation_markdown(report, heading_level=2, include_details=True):
    heading = "#" * heading_level
    lines = [
        f"{heading} 解析器生成",
        "",
        f"- 源语法文件: `{report.grammar_path}`",
        f"- 输出解析器: `{report.output_path}`",
        f"- 生成时间: `{report.generated_at}`",
        f"- 总耗时: `{report.duration_seconds:.3f}` 秒",
        f"- 语法行数: `{report.line_count}`",
        f"- Token 缓存: `{report.token_count}`",
        f"- Parser 缓存: `{report.parser_cache_size}`",
        ""
    ]

    if report.duration_seconds:
        lines.append(f"- 处理速度: `{report.line_count / report.duration_seconds:.0f}` 行/秒")
        lines.append("")

    if not include_details:
        recursive_sccs = [scc for scc in report.first_sccs if scc["status"] != "普通"]
        if recursive_sccs:
            lines.extend([
                f"{heading}# 递归规则摘要",
                "",
                "| 规则 | 类型 | 领导者 |",
                "| --- | --- | --- |"
            ])
            for scc in recursive_sccs:
                lines.append(
                    f"| `{_escape_markdown_table_cell(scc['rules'])}` | "
                    f"{_escape_markdown_table_cell(scc['status'])} | "
                    f"`{_escape_markdown_table_cell(scc['leaders'])}` |"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend([
        f"{heading}# 原始语法结构",
        "",
        "```text",
        report.raw_grammar,
        "```",
        "",
        f"{heading}# 干净语法代码",
        "",
        "```text",
        report.clean_grammar,
        "```",
        "",
        f"{heading}# 首项图",
        "",
        "| 源规则 | 目标规则 |",
        "| --- | --- |"
    ])

    for src, dsts in report.first_graph.items():
        dst_text = ", ".join(dsts) if dsts else "-"
        lines.append(
            f"| `{_escape_markdown_table_cell(src)}` | "
            f"`{_escape_markdown_table_cell(dst_text)}` |"
        )

    lines.extend([
        "",
        f"{heading}# 首项强连通分量",
        "",
        "| 规则 | 类型 | 领导者 |",
        "| --- | --- | --- |"
    ])

    for scc in report.first_sccs:
        lines.append(
            f"| `{_escape_markdown_table_cell(scc['rules'])}` | "
            f"{_escape_markdown_table_cell(scc['status'])} | "
            f"`{_escape_markdown_table_cell(scc['leaders'])}` |"
        )

    lines.append("")
    return "\n".join(lines)


def format_runtime_error(error: VBCRuntimeError):
    print("错误跟踪:")
    for frame in error.traceback:
        print(f'  在文件 "{frame.filepath}" 中, 第 {frame.line} 行, {frame.scope_name} 中:')
        for source in frame.source_line_context or []:
            print(f"    {source}")
    print(error.message)


def compile_source_file(
        filename,
        log_modules=None,
        dump_modules=None,
        dump_path=None,
        execute=True,
        refresh_parser=False,
        show_warnings=True
    ):
    """执行单文件编译/运行，并按需输出 dump 与编译告警。"""
    log_modules = log_modules or set()
    dump_modules = dump_modules or set()
    log_compile = "all" in log_modules or "compile" in log_modules
    log_vm = "all" in log_modules or "vm" in log_modules
    log_parser = "all" in log_modules or "parser" in log_modules
    dump_all = "all" in dump_modules
    dump_parser = dump_all or "parser" in dump_modules
    dump_preprocess = dump_all or "preprocess" in dump_modules
    dump_tokens = dump_all or "tokens" in dump_modules
    dump_ast = dump_all or "ast" in dump_modules
    dump_opcode = dump_all or "opcode" in dump_modules
    dump_const = dump_all or "const" in dump_modules
    dump_label = dump_all or "label" in dump_modules
    dump_vm = dump_all or "vm" in dump_modules

    compilation_result = None
    parser_generation_report = None
    vm_debug_logs = []
    dump_processed_code = None
    dump_tokens_data = None
    captured_error = None
    compile_warnings = []

    if log_compile:
        print(f"编译源代码文件: {filename}")

    try:
        if log_parser or dump_parser:
            parser_needs_generation = refresh_parser or not os.path.exists(default_parser_output)
            if parser_needs_generation:
                parser_generation_report = generate_parser(grammar_file, default_parser_output)
                if log_parser:
                    print(_format_parser_generation_markdown(parser_generation_report, heading_level=2, include_details=False))
                refresh_parser = False

        if dump_path and (dump_preprocess or dump_tokens):
            with open(filename, "r", encoding="utf-8") as source_file:
                source_code = source_file.read()
            from verbose_c.preprocessor.preprocessor import Preprocessor
            dump_processed_code = Preprocessor().process(source_code, filename)
            if dump_tokens:
                from verbose_c.parser.lexer.tokenizer import Tokenizer
                dump_tokens_data = Tokenizer(filename, dump_processed_code).tokens

        if log_compile:
            print("调用核心编译引擎...")
        compilation_result = compile_module(
            file_path=filename,
            refresh_parser=refresh_parser,
            need_tokens=dump_tokens,
            need_ast=dump_ast,
            need_processed_code=dump_preprocess
        )
        if parser_generation_report is None:
            parser_generation_report = compilation_result.parser_generation_report
        compile_warnings = compilation_result.warnings or []
        if show_warnings and compile_warnings:
            for warning_line in compile_warnings:
                print(f"警告: {warning_line}")

        if log_compile:
            print("编译完成。")

        if execute:
            if log_vm:
                print("\n执行字节码...\n")
            from verbose_c.vm.core import VBCVirtualMachine
            log_collector = vm_debug_logs if dump_vm and dump_path else None

            vm = VBCVirtualMachine(debug_log_collector=log_collector)
            vm.excute(
                bytecode=compilation_result.bytecode,
                constants=compilation_result.constant_pool,
                source_path=filename,
                lineno_table=compilation_result.lineno_table,
                source_code=compilation_result.processed_code.split("\n")
            )
            if log_vm:
                print("程序执行完成")

    except VBCRuntimeError as e:
        captured_error = e
        format_runtime_error(e)
    except VBCCompileError as e:
        captured_error = e
        print(f"编译错误: 文件 {e.filepath}")
        for error_line in e.message.split('\n'):
            print(f"  - {error_line}")
        compile_warnings = e.warnings or []
        if show_warnings and compile_warnings:
            for warning_line in compile_warnings:
                print(f"警告: {warning_line}")
    except Exception as e:
        captured_error = e
        print(f"发生了一个意外的内部错误: {e}")
        traceback.print_exc()
    finally:
        if dump_path:
            processed_code_to_dump = None
            if compilation_result is not None and compilation_result.processed_code:
                processed_code_to_dump = compilation_result.processed_code
            elif dump_processed_code:
                processed_code_to_dump = dump_processed_code

            tokens_to_dump = None
            if compilation_result is not None and compilation_result.tokens:
                tokens_to_dump = compilation_result.tokens
            elif dump_tokens_data:
                tokens_to_dump = dump_tokens_data

            ast_node_to_dump = compilation_result.ast_node if compilation_result is not None else None
            bytecode_to_dump = compilation_result.bytecode if compilation_result is not None else []
            const_pool_to_dump = compilation_result.constant_pool if compilation_result is not None else []
            labels_to_dump = compilation_result.labels if compilation_result is not None else {}
            function_results_to_dump = compilation_result.function_compilation_results if compilation_result is not None else {}

            with open(dump_path, 'w', encoding='utf-8') as f:
                f.write(f"# {filename} Verbose-C Dump\n\n")
                toc_lines = [
                    "- [基本信息](#基本信息)"
                ]
                if captured_error is not None:
                    toc_lines.append("- [错误信息](#错误信息)")
                if dump_parser and parser_generation_report:
                    toc_lines.append("- [解析器生成](#解析器生成)")
                if dump_preprocess and processed_code_to_dump:
                    toc_lines.append("- [预处理代码](#预处理代码)")
                if dump_tokens and tokens_to_dump:
                    toc_lines.append("- [Token 序列](#token-序列)")
                if dump_ast and ast_node_to_dump:
                    toc_lines.append("- [AST 结构](#ast-结构)")
                if dump_opcode and bytecode_to_dump:
                    toc_lines.append("- [操作码](#操作码)")
                if dump_const and const_pool_to_dump:
                    toc_lines.append("- [常量池](#常量池)")
                if dump_label and labels_to_dump:
                    toc_lines.append("- [标签](#标签)")
                if dump_opcode and function_results_to_dump:
                    toc_lines.append("- [函数编译结果](#函数编译结果)")
                if dump_vm and vm_debug_logs:
                    toc_lines.append("- [虚拟机执行记录](#虚拟机执行记录)")

                _write_dump_toc(f, toc_lines)
                f.write("## 基本信息\n\n")
                f.write(f"- 源文件: `{filename}`\n")
                f.write(f"- 生成时间: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n")
                f.write(f"- 编译结果: `{'失败' if captured_error else '成功'}`\n\n")

                if captured_error is not None:
                    _write_error_dump_section(f, captured_error)

                if dump_parser and parser_generation_report:
                    f.write(_format_parser_generation_markdown(parser_generation_report, heading_level=2, include_details=True))

                if dump_preprocess and processed_code_to_dump:
                    f.write("## 预处理代码\n\n")
                    f.write("```c\n")
                    f.write(processed_code_to_dump)
                    if not processed_code_to_dump.endswith("\n"):
                        f.write("\n")
                    f.write("```\n\n")

                if dump_tokens and tokens_to_dump:
                    f.write("## Token 序列\n\n")
                    f.write("```text\n")
                    for token in tokens_to_dump:
                        f.write(f"{token}\n")
                    f.write("```\n\n")

                if dump_ast and ast_node_to_dump:
                    from verbose_c.parser.parser.parser import ast_dump
                    f.write("## AST 结构\n\n")
                    f.write("```text\n")
                    f.write(ast_dump(ast_node_to_dump, indent=4))
                    f.write("\n```\n\n")

                if dump_opcode and bytecode_to_dump:
                    f.write("## 操作码\n\n")
                    f.write("| 索引 | 指令 |\n")
                    f.write("| --- | --- |\n")
                    for i, instruction in enumerate(bytecode_to_dump):
                        if len(instruction) == 1:
                            f.write(f"| {i} | `{instruction[0].name}` |\n")
                        else:
                            opcode_text = f"{instruction[0].name} {instruction[1]!r}"
                            opcode_text = opcode_text.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")
                            f.write(f"| {i} | `{opcode_text}` |\n")
                    f.write("\n")

                if dump_const and const_pool_to_dump:
                    f.write("## 常量池\n\n")
                    f.write("| 索引 | 值 |\n")
                    f.write("| --- | --- |\n")
                    for i, constant in enumerate(const_pool_to_dump):
                        constant_text = repr(constant).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")
                        f.write(f"| {i} | `{constant_text}` |\n")
                    f.write("\n")

                if dump_label and labels_to_dump:
                    f.write("## 标签\n\n")
                    f.write("| 标签 | 位置 |\n")
                    f.write("| --- | --- |\n")
                    for lbl, pos in labels_to_dump.items():
                        f.write(f"| `{lbl}` | {pos} |\n")
                    f.write("\n")

                if dump_opcode and function_results_to_dump:
                    f.write("## 函数编译结果\n\n")
                    for func_name, result in function_results_to_dump.items():
                        f.write(f"### 函数 `{func_name}`\n\n")
                        if result.get('bytecode'):
                            f.write("#### 操作码\n\n")
                            f.write("| 索引 | 指令 |\n")
                            f.write("| --- | --- |\n")
                            for i, instruction in enumerate(result['bytecode']):
                                if len(instruction) == 1:
                                    f.write(f"| {i} | `{instruction[0].name}` |\n")
                                else:
                                    opcode_text = f"{instruction[0].name} {instruction[1]!r}"
                                    opcode_text = opcode_text.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")
                                    f.write(f"| {i} | `{opcode_text}` |\n")
                            f.write("\n")
                        if result.get('constants'):
                            f.write("#### 常量池\n\n")
                            f.write("| 索引 | 值 |\n")
                            f.write("| --- | --- |\n")
                            for i, constant in enumerate(result['constants']):
                                constant_text = repr(constant).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")
                                f.write(f"| {i} | `{constant_text}` |\n")
                            f.write("\n")
                        if result.get('labels'):
                            f.write("#### 标签\n\n")
                            f.write("| 标签 | 位置 |\n")
                            f.write("| --- | --- |\n")
                            for label, pos in result['labels'].items():
                                f.write(f"| `{label}` | {pos} |\n")
                            f.write("\n")

                if dump_vm and vm_debug_logs:
                    f.write("## 虚拟机执行记录\n\n")
                    f.write("```text\n")
                    for log_entry in vm_debug_logs:
                        f.write(log_entry + "\n")
                    f.write("```\n")

            print(f"\n运行记录已保存到：{dump_path}")


if __name__ == "__main__":
    main()
