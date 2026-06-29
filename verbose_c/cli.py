import argparse
import os
import time
import traceback
from verbose_c.engine.engine import compile_module, generate_parser
from verbose_c.error import VBCRuntimeError, VBCCompileError, TracebackFrame

default_parser_output = "parser.py"

def parse_args():
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )
    
    parser.add_argument("filename", help="需要编译的文件（.vbc源代码文件或.gram语法文件）")
    parser.add_argument("--log", help="启用命令行日志输出", action="store_true")
    parser.add_argument("--verbose", help="输出详细日志，仅在 --log 时生效", action="store_true")
    parser.add_argument("--dump", help="将中间产物写入文件（仅输出到文件，不输出到命令行）")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    parser.add_argument("--compile-only", help="只编译不执行源代码", action="store_true")
    parser.add_argument("--debug-vm", help="开启虚拟机调试模式", action="store_true")
    parser.add_argument("-rp", "--refresh-parser", help="重新生成解析器", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.verbose and not args.log:
        print("错误: --verbose 仅在指定 --log 时生效")
        return
    
    if args.filename:
        if not os.path.exists(args.filename):
            print(f"错误: 文件 '{args.filename}' 不存在")
            return
    
    if args.compile_parser:
        # 直接调用引擎函数来编译语法文件
        try:
            from verbose_c.engine.engine import grammar_file
            if args.log:
                print(f"开始编译语法文件: {grammar_file}")
            generate_parser(grammar_file, default_parser_output, None)
            if args.log:
                print(f"语法文件 '{grammar_file}' 编译成功.")
        except Exception as e:
            print(f"编译语法文件时发生错误: {e}")
            traceback.print_exc()
    else:
        # 编译源代码文件
        compile_source_file(
            filename=args.filename,
            log=args.log,
            verbose=args.verbose,
            dump=args.dump,
            execute=not args.compile_only,
            debug_vm=args.debug_vm,
            refresh_parser=args.refresh_parser
        )
        
def format_runtime_error(error: VBCRuntimeError):
    """
    格式化并打印 VBCRuntimeError，模仿 Python 的 traceback 格式。
    """
    print("错误跟踪:")
    for frame in error.traceback:
        print(f'  在文件 "{frame.filepath}" 中, 第 {frame.line} 行, {frame.scope_name} 中:')
        for source in frame.source_line_context or []:
            print(f"    {source}")
        # TODO: 增加打印源码行和箭头的功能
    print(error.message)


def compile_source_file(
        filename, 
        log=False,
        verbose=False,
        dump=None,
        execute=True,
        debug_vm=False,
        refresh_parser=False
    ):
    """
    编译源代码文件，处理日志记录和执行。
    """
    if log:
        print(f"编译源代码文件: {filename}")
    
    try:
        if log and verbose:
            print("调用核心编译引擎...")
        need_intermediate = bool(dump)
        compilation_result = compile_module(
            file_path=filename, 
            refresh_parser=refresh_parser,
            need_tokens=need_intermediate,
            need_ast=need_intermediate,
            need_processed_code=need_intermediate,
            log_parser_gen_path=None
        )
        if log:
            print("编译完成。")

        # 执行字节码
        vm_debug_logs = []
        if execute:
            if log and verbose:
                print("\n执行字节码...\n")
            from verbose_c.vm.core import VBCVirtualMachine
            log_collector = vm_debug_logs if debug_vm and (dump is not None) else None
            
            vm = VBCVirtualMachine(debug_log_collector=log_collector)
            vm.excute(
                bytecode=compilation_result.bytecode, 
                constants=compilation_result.constant_pool,
                source_path=filename,
                lineno_table=compilation_result.lineno_table,
                source_code=compilation_result.processed_code.split("\n")
            )
            if log:
                print("程序执行完成")

        # 将中间产物写入文件
        if dump:
            with open(dump, 'w', encoding='utf-8') as f:
                f.write("# Verbose-C Dump\n")
                f.write(f"# 源文件: {filename}\n")
                f.write(f"# 生成时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
                
                if compilation_result.processed_code:
                    f.write("\n=== 预处理代码 ===\n")
                    f.write(compilation_result.processed_code)
                    f.write("\n")

                if compilation_result.tokens:
                    f.write("\n=== Token序列 ===\n")
                    for token in compilation_result.tokens:
                        f.write(f"{token}\n")
                
                if compilation_result.ast_node:
                    from verbose_c.parser.parser.parser import ast_dump
                    f.write("\n=== AST结构 ===\n")
                    f.write(ast_dump(compilation_result.ast_node, indent=4))
                    f.write("\n")

                f.write("\n=== 操作码 ===\n")
                for i, instruction in enumerate(compilation_result.bytecode):
                    if len(instruction) == 1:
                        f.write(f"{i:4d}: {instruction[0].name}\n")
                    else:
                        f.write(f"{i:4d}: {instruction[0].name} {instruction[1]}\n")
                
                f.write(f"\n=== 常量池 ===\n")
                for i, constant in enumerate(compilation_result.constant_pool):
                    f.write(f"{i:4d}: {repr(constant)}\n")
                
                f.write(f"\n=== 标签 ===\n")
                for lbl, pos in compilation_result.labels.items():
                    f.write(f"{lbl}: {pos}\n")

                if compilation_result.function_compilation_results:
                    f.write("\n\n" + "="*15 + " 函数编译结果 " + "="*15 + "\n")
                    for func_name, result in compilation_result.function_compilation_results.items():
                        f.write(f"\n--- 函数: {func_name} ---\n")
                        if result.get('bytecode'):
                            f.write("  操作码:\n")
                            for i, instruction in enumerate(result['bytecode']):
                                if len(instruction) == 1:
                                    f.write(f"    {i:4d}: {instruction[0].name}\n")
                                else:
                                    f.write(f"    {i:4d}: {instruction[0].name} {instruction[1]}\n")
                        if result.get('constants'):
                            f.write("  常量池:\n")
                            for i, constant in enumerate(result['constants']):
                                f.write(f"    {i:4d}: {repr(constant)}\n")
                        if result.get('labels'):
                            f.write("  标签:\n")
                            for label, pos in result['labels'].items():
                                f.write(f"    {label}: {pos}\n")
                    f.write("\n" + "="*40 + "\n")

                if vm_debug_logs:
                    f.write("\n=== 虚拟机执行记录 ===\n")
                    for log_entry in vm_debug_logs:
                        f.write(log_entry + "\n")

            if log:
                print(f"中间产物已保存到: {dump}")

    except VBCRuntimeError as e:
        # 捕获我们自定义的运行时错误并格式化输出
        format_runtime_error(e)
    except VBCCompileError as e:
        # 格式化并打印编译错误
        print(f"编译错误: 文件 {e.filepath}")
        for error_line in e.message.split('\n'):
            print(f"  - {error_line}")
    except Exception as e:
        # 对于其他意外的 Python 异常，仍然打印完整的 traceback 以便调试
        print(f"发生了一个意外的内部错误: {e}")
        traceback.print_exc()



if __name__ == "__main__":
    main()
