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
    parser.add_argument("--log", help="输出日志文件名")
    parser.add_argument("--log-parser-gen", help="记录语法分析器生成日志")
    parser.add_argument("-p", "--preprocess", help="输出预处理后的代码到日志文件", action="store_true")
    parser.add_argument("-t", "--tokenization", help="输出token序列", action="store_true")
    parser.add_argument("-a", "--ast", help="输出AST", action="store_true")
    parser.add_argument("--opcode", help="输出操作码", action="store_true")
    parser.add_argument("-c", "--const", help="输出常量池", action="store_true")
    parser.add_argument("-l", "--label", help="输出标签", action="store_true")
    parser.add_argument("-oa", "--out-all", help="输出所有内容（token, AST, 操作码, 常量池, 标签）", action="store_true")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    parser.add_argument("--compile-only", help="只编译不执行源代码", action="store_true")
    parser.add_argument("--debug-vm", help="开启虚拟机调试模式", action="store_true")
    parser.add_argument("-rp", "--refresh-parser", help="重新生成解析器", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    
    if args.filename:
        if not os.path.exists(args.filename):
            print(f"错误: 文件 '{args.filename}' 不存在")
            return
    
    if args.compile_parser:
        # 直接调用引擎函数来编译语法文件
        try:
            from verbose_c.engine.engine import grammar_file
            generate_parser(grammar_file, default_parser_output, args.log_parser_gen)
            print(f"语法文件 '{grammar_file}' 编译成功.")
        except Exception as e:
            print(f"编译语法文件时发生错误: {e}")
            traceback.print_exc()
    else:
        # 编译源代码文件
        compile_source_file(
            filename=args.filename,
            log=args.log,
            tokenization=args.tokenization,
            ast=args.ast,
            opcode=args.opcode,
            const=args.const,
            label=args.label,
            out_all=args.out_all,
            preprocess=args.preprocess,
            execute=not args.compile_only,
            debug_vm=args.debug_vm,
            refresh_parser=args.refresh_parser,
            log_parser_gen=args.log_parser_gen
        )
        
def format_runtime_error(error: VBCRuntimeError):
    """
    格式化并打印 VBCRuntimeError，模仿 Python 的 traceback 格式。
    """
    print("错误栈跟踪:")
    for frame in error.traceback:
        print(f'  在文件 "{frame.filepath}" 中, 第 {frame.line} 行, {frame.scope_name} 中')
        # TODO: 增加打印源码行的功能
    print(error.message)


def compile_source_file(
        filename, 
        log=None,
        tokenization=False,
        ast=False,
        opcode=False,
        const=False,
        label=False,
        out_all=False,
        preprocess=False,
        execute=True,
        debug_vm=False,
        refresh_parser=False,
        log_parser_gen=None
    ):
    """
    编译源代码文件，处理日志记录和执行。
    """
    print(f"编译源代码文件: {filename}")
    
    try:
        print("调用核心编译引擎...")
        need_intermediate = bool(log)
        compilation_result = compile_module(
            file_path=filename, 
            refresh_parser=refresh_parser,
            need_tokens=need_intermediate,
            need_ast=need_intermediate,
            need_processed_code=need_intermediate and (preprocess or out_all),
            log_parser_gen_path=log_parser_gen
        )
        print("编译完成。")

        # 执行字节码
        vm_debug_logs = []
        if execute:
            print("\n执行字节码...")
            from verbose_c.vm.core import VBCVirtualMachine
            log_collector = vm_debug_logs if debug_vm and log else None
            
            vm = VBCVirtualMachine(debug_log_collector=log_collector)
            vm.excute(
                bytecode=compilation_result.bytecode, 
                constants=compilation_result.constant_pool,
                source_path=filename
            )
            print("程序执行完成")

        # 写入日志文件
        if log:
            with open(log, 'w', encoding='utf-8') as f:
                f.write("# Verbose-C 编译日志\n")
                f.write(f"# 源文件: {filename}\n")
                f.write(f"# 生成时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
                
                if preprocess or out_all:
                    if compilation_result.processed_code:
                        f.write("\n=== 预处理代码 ===\n")
                        f.write(compilation_result.processed_code)
                        f.write("\n")

                if tokenization or out_all:
                    if compilation_result.tokens:
                        f.write("\n=== Token序列 ===\n")
                        for token in compilation_result.tokens:
                            f.write(f"{token}\n")
                
                if ast or out_all:
                    if compilation_result.ast_node:
                        from verbose_c.parser.parser.parser import ast_dump
                        f.write("\n=== AST结构 ===\n")
                        f.write(ast_dump(compilation_result.ast_node, indent=4))
                        f.write("\n")

                if opcode or out_all:
                    f.write("\n=== 操作码 ===\n")
                    for i, instruction in enumerate(compilation_result.bytecode):
                        if len(instruction) == 1:
                            f.write(f"{i:4d}: {instruction[0].name}\n")
                        else:
                            f.write(f"{i:4d}: {instruction[0].name} {instruction[1]}\n")
                
                if const or out_all:
                    f.write(f"\n=== 常量池 ===\n")
                    for i, constant in enumerate(compilation_result.constant_pool):
                        f.write(f"{i:4d}: {constant}\n")
                
                if label or out_all:
                    f.write(f"\n=== 标签 ===\n")
                    for lbl, pos in compilation_result.labels.items():
                        f.write(f"{lbl}: {pos}\n")

                if compilation_result.function_compilation_results and (opcode or out_all):
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
                                f.write(f"    {i:4d}: {constant}\n")
                        if result.get('labels'):
                            f.write("  标签:\n")
                            for label, pos in result['labels'].items():
                                f.write(f"    {label}: {pos}\n")
                    f.write("\n" + "="*40 + "\n")

                if debug_vm or out_all:
                    if vm_debug_logs:
                        f.write("\n=== 虚拟机执行记录 ===\n")
                        for log_entry in vm_debug_logs:
                            f.write(log_entry + "\n")

            print(f"\n编译输出已保存到: {log}")

    except VBCRuntimeError as e:
        # 捕获我们自定义的运行时错误并格式化输出
        format_runtime_error(e)
    except VBCCompileError as e:
        # TODO: 完善编译错误的格式化输出
        print(f"编译错误: 文件 {e.filepath}, 行 {e.line}")
        print(f"  {e.message}")
    except Exception as e:
        # 对于其他意外的 Python 异常，仍然打印完整的 traceback 以便调试
        print(f"发生了一个意外的内部错误: {e}")
        traceback.print_exc()



if __name__ == "__main__":
    main()
