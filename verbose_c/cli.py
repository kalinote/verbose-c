import argparse
import os
import re
import time
import traceback
from verbose_c.engine.engine import compile_module, generate_parser
from verbose_c.error import VBCRuntimeError, VBCCompileError

default_parser_output = "parser.py"


def parse_args():
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )

    parser.add_argument("filename", help="需要编译的文件（.vbc源代码文件或.gram语法文件）")
    parser.add_argument("--log", nargs="?", const="all", help="按模块输出命令行日志（模块: compile, vm, parser, all；默认 all）")
    parser.add_argument("--dump", nargs="?", const="all", help="按模块写入中间产物（模块: preprocess, tokens, ast, opcode, const, label, vm, all；默认 all）")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    parser.add_argument("--compile-only", help="只编译不执行源代码", action="store_true")
    parser.add_argument("--debug-vm", help="开启虚拟机调试模式", action="store_true")
    parser.add_argument("-rp", "--refresh-parser", help="重新生成解析器", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    log_modules = set()
    dump_modules = set()
    allowed_log_modules = {"compile", "vm", "parser", "all"}
    allowed_dump_modules = {"preprocess", "tokens", "ast", "opcode", "const", "label", "vm", "all"}

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
        try:
            from verbose_c.engine.engine import grammar_file
            if "all" in log_modules or "parser" in log_modules:
                print(f"开始编译语法文件: {grammar_file}")
            generate_parser(grammar_file, default_parser_output, None)
            if "all" in log_modules or "parser" in log_modules:
                print(f"语法文件 '{grammar_file}' 编译成功.")
        except Exception as e:
            print(f"编译语法文件时发生错误: {e}")
            traceback.print_exc()
    else:
        dump_path = None
        if dump_modules:
            safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', args.filename)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            os.makedirs("dumps", exist_ok=True)
            dump_path = os.path.join("dumps", f"{safe_name}_{timestamp}.md")

        compile_source_file(
            filename=args.filename,
            log_modules=log_modules,
            dump_modules=dump_modules,
            dump_path=dump_path,
            execute=not args.compile_only,
            debug_vm=args.debug_vm,
            refresh_parser=args.refresh_parser
        )


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
        debug_vm=False,
        refresh_parser=False
    ):
    log_modules = log_modules or set()
    dump_modules = dump_modules or set()
    log_compile = "all" in log_modules or "compile" in log_modules
    log_vm = "all" in log_modules or "vm" in log_modules
    dump_all = "all" in dump_modules
    dump_preprocess = dump_all or "preprocess" in dump_modules
    dump_tokens = dump_all or "tokens" in dump_modules
    dump_ast = dump_all or "ast" in dump_modules
    dump_opcode = dump_all or "opcode" in dump_modules
    dump_const = dump_all or "const" in dump_modules
    dump_label = dump_all or "label" in dump_modules
    dump_vm = dump_all or "vm" in dump_modules

    if log_compile:
        print(f"编译源代码文件: {filename}")

    try:
        if log_compile:
            print("调用核心编译引擎...")
        compilation_result = compile_module(
            file_path=filename,
            refresh_parser=refresh_parser,
            need_tokens=dump_tokens,
            need_ast=dump_ast,
            need_processed_code=dump_preprocess,
            log_parser_gen_path=None
        )
        if log_compile:
            print("编译完成。")

        vm_debug_logs = []
        if execute:
            if log_vm:
                print("\n执行字节码...\n")
            from verbose_c.vm.core import VBCVirtualMachine
            log_collector = vm_debug_logs if debug_vm and dump_vm and dump_path else None

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

        if dump_path:
            with open(dump_path, 'w', encoding='utf-8') as f:
                f.write(f"# {filename} Verbose-C Dump\n\n")
                toc_lines = [
                    "- [基本信息](#基本信息)"
                ]
                if dump_preprocess and compilation_result.processed_code:
                    toc_lines.append("- [预处理代码](#预处理代码)")
                if dump_tokens and compilation_result.tokens:
                    toc_lines.append("- [Token 序列](#token-序列)")
                if dump_ast and compilation_result.ast_node:
                    toc_lines.append("- [AST 结构](#ast-结构)")
                if dump_opcode:
                    toc_lines.append("- [操作码](#操作码)")
                if dump_const:
                    toc_lines.append("- [常量池](#常量池)")
                if dump_label:
                    toc_lines.append("- [标签](#标签)")
                if dump_opcode and compilation_result.function_compilation_results:
                    toc_lines.append("- [函数编译结果](#函数编译结果)")
                if dump_vm and vm_debug_logs:
                    toc_lines.append("- [虚拟机执行记录](#虚拟机执行记录)")

                f.write("## 目录\n\n")
                f.write("\n".join(toc_lines))
                f.write("\n\n")
                f.write("## 基本信息\n\n")
                f.write(f"- 源文件: `{filename}`\n")
                f.write(f"- 生成时间: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n\n")

                if dump_preprocess and compilation_result.processed_code:
                    f.write("## 预处理代码\n\n")
                    f.write("```c\n")
                    f.write(compilation_result.processed_code)
                    if not compilation_result.processed_code.endswith("\n"):
                        f.write("\n")
                    f.write("```\n\n")

                if dump_tokens and compilation_result.tokens:
                    f.write("## Token 序列\n\n")
                    f.write("```text\n")
                    for token in compilation_result.tokens:
                        f.write(f"{token}\n")
                    f.write("```\n\n")

                if dump_ast and compilation_result.ast_node:
                    from verbose_c.parser.parser.parser import ast_dump
                    f.write("## AST 结构\n\n")
                    f.write("```text\n")
                    f.write(ast_dump(compilation_result.ast_node, indent=4))
                    f.write("\n```\n\n")

                if dump_opcode:
                    f.write("## 操作码\n\n")
                    f.write("| 索引 | 指令 |\n")
                    f.write("| --- | --- |\n")
                    for i, instruction in enumerate(compilation_result.bytecode):
                        if len(instruction) == 1:
                            f.write(f"| {i} | `{instruction[0].name}` |\n")
                        else:
                            opcode_text = f"{instruction[0].name} {instruction[1]!r}"
                            opcode_text = opcode_text.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")
                            f.write(f"| {i} | `{opcode_text}` |\n")
                    f.write("\n")

                if dump_const:
                    f.write("## 常量池\n\n")
                    f.write("| 索引 | 值 |\n")
                    f.write("| --- | --- |\n")
                    for i, constant in enumerate(compilation_result.constant_pool):
                        constant_text = repr(constant).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")
                        f.write(f"| {i} | `{constant_text}` |\n")
                    f.write("\n")

                if dump_label:
                    f.write("## 标签\n\n")
                    f.write("| 标签 | 位置 |\n")
                    f.write("| --- | --- |\n")
                    for lbl, pos in compilation_result.labels.items():
                        f.write(f"| `{lbl}` | {pos} |\n")
                    f.write("\n")

                if dump_opcode and compilation_result.function_compilation_results:
                    f.write("## 函数编译结果\n\n")
                    for func_name, result in compilation_result.function_compilation_results.items():
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

    except VBCRuntimeError as e:
        format_runtime_error(e)
    except VBCCompileError as e:
        print(f"编译错误: 文件 {e.filepath}")
        for error_line in e.message.split('\n'):
            print(f"  - {error_line}")
    except Exception as e:
        print(f"发生了一个意外的内部错误: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
