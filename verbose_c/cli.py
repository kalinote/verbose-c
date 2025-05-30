import argparse
import os
import sys
import time
import traceback
import importlib.util
from verbose_c.parser.ppg.build import build_python_parser_and_generator
from verbose_c.parser.ppg.validator import validate_grammar
from verbose_c.parser.lexer.lexer import Lexer
from verbose_c.parser.lexer.tokenizer import Tokenizer
from verbose_c.compiler.symbol import SymbolTable
from verbose_c.compiler.enum import ScopeType
from verbose_c.compiler.opcode_generator import OpcodeGenerator

def parse_args():
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )
    
    parser.add_argument("filename", help="需要编译的文件（.vbc源代码文件或.gram语法文件）")
    parser.add_argument("-o", "--output", help="输出文件名")
    parser.add_argument("-v", "--verbose", help="显示详细信息", action="store_true")
    parser.add_argument("-l", "--log", help="记录编译过程")
    parser.add_argument("-t", "--tokenization", help="仅计算文件 token", action="store_true")
    parser.add_argument("--gen-parser", help="生成解析器模式（用于.gram文件）", action="store_true")
    parser.add_argument("--opcode", help="输出操作码到指定文件")
    return parser.parse_args()


def main():
    args = parse_args()
    
    if args.filename:
        if not os.path.exists(args.filename):
            print(f"错误: 文件 '{args.filename}' 不存在")
            return
    
    if args.tokenization:
        from verbose_c.parser.lexer.lexer import Lexer
        with open(args.filename, "r", encoding="utf-8") as f:
            source = f.read()
        lexer = Lexer(args.filename, source)
        for token in lexer.tokenize():
            print(token)
        return
    
    # 判断文件类型并选择处理方式
    file_ext = os.path.splitext(args.filename)[1].lower()
    
    if file_ext == '.gram' or args.gen_parser:
        # 语法文件，生成解析器
        compile_file(args.filename, args.output, args.verbose, args.log)
    elif file_ext == '.vbc':
        # 源代码文件，编译到操作码
        compile_source_file(args.filename, args.verbose, args.opcode)
    else:
        print(f"错误: 不支持的文件类型 '{file_ext}'，支持的文件类型: .gram, .vbc")
        
def compile_source_file(filename, verbose=False, opcode_output=None):
    """
    编译源代码文件到操作码
    """
    print(f"编译源代码文件: {filename}")
    
    # 确保解析器存在
    parser_path = "parser.py"
    if not os.path.exists(parser_path):
        print("解析器不存在，正在生成解析器...")
        grammar_file = "Grammar/verbose_c.gram"
        if not os.path.exists(grammar_file):
            print(f"错误: 语法文件 '{grammar_file}' 不存在")
            return
        compile_file(grammar_file, parser_path, verbose)
        
    try:
        # 动态导入生成的解析器
        spec = importlib.util.spec_from_file_location("parser", parser_path)
        parser_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parser_module)
        
        # 读取源代码
        with open(filename, "r", encoding="utf-8") as f:
            source_code = f.read()
        
        # 创建tokenizer和parser
        tokenizer = Tokenizer(filename, source_code, verbose=verbose)
        parser = parser_module.GeneratedParser(tokenizer, verbose=verbose)
        
        # 解析生成AST
        print("解析源代码生成AST...")
        ast = parser.start()
        
        if ast is None:
            print("错误: 解析失败")
            return
            
        if verbose:
            from verbose_c.parser.parser.parser import ast_dump
            print("AST结构:")
            print(ast_dump(ast, indent=2))
            print()
        
        # 创建符号表
        symbol_table = SymbolTable(ScopeType.GLOBAL)
        
        # 生成操作码
        print("生成操作码...")
        opcode_gen = OpcodeGenerator(symbol_table)
        opcode_gen.visit(ast)
        
        # 输出结果
        print("\n=== 生成的操作码 ===")
        for i, instruction in enumerate(opcode_gen.bytecode):
            if len(instruction) == 1:
                print(f"{i:4d}: {instruction[0].name}")
            else:
                print(f"{i:4d}: {instruction[0].name} {instruction[1]}")
        
        print(f"\n=== 常量池 ===")
        for i, constant in enumerate(opcode_gen.constant_pool):
            print(f"{i:4d}: {constant!r}")
        
        print(f"\n=== 标签 ===")
        for label, pos in opcode_gen.labels.items():
            print(f"{label}: {pos}")
            
        # 如果指定了输出文件，写入操作码
        if opcode_output:
            write_opcode_to_file(opcode_output, opcode_gen)
            print(f"\n操作码已输出到: {opcode_output}")
            
    except Exception as e:
        print(f"编译过程中发生错误: {e}")
        if verbose:
            traceback.print_exc()

def write_opcode_to_file(filename, opcode_gen):
    """
    将操作码输出到文件
    """
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("# Verbose-C 操作码文件\n")
        f.write("# 生成时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
        
        f.write("=== 操作码 ===\n")
        for i, instruction in enumerate(opcode_gen.bytecode):
            if len(instruction) == 1:
                f.write(f"{i:4d}: {instruction[0].name}\n")
            else:
                f.write(f"{i:4d}: {instruction[0].name} {instruction[1]}\n")
        
        f.write(f"\n=== 常量池 ===\n")
        for i, constant in enumerate(opcode_gen.constant_pool):
            f.write(f"{i:4d}: {constant!r}\n")
        
        f.write(f"\n=== 标签 ===\n")
        for label, pos in opcode_gen.labels.items():
            f.write(f"{label}: {pos}\n")

def compile_file(filename, output, verbose, log=None):
    """
    编译语法文件生成解析器
    """
    t0 = time.time()
    grammar, parser, tokenizer, gen = generate_python_code(filename, output, verbose)
    t1 = time.time()
    
    validate_grammar(grammar)
    
    if log:
        if os.path.exists(log):
            os.remove(log)

        with open(log, "w", encoding="utf-8") as f:
            f.write("原始语法:\n")
            for line in repr(grammar).splitlines():
                f.write(" " + line + "\n")
                
            f.write("--------------------------------\n")
            f.write("干净语法:\n")
            for line in str(grammar).splitlines():
                f.write(" " + line + "\n")
            
            f.write("--------------------------------\n")
            f.write("首项图:\n")
            for src, dsts in gen.first_graph.items():
                f.write(f"  {src} -> {', '.join(dsts)}\n")
            
            f.write("--------------------------------\n")
            f.write("首项强连通分量:\n")
            for scc in gen.first_sccs:
                f.write(" " + str(scc))
                if len(scc) > 1:
                    f.write(
                        f"  # 间接左递归; 领导者: {', '.join(name for name in scc if grammar.rules[name].leader)}\n"
                    )
                else:
                    name = next(iter(scc))
                    if name in gen.first_graph[name]:
                        f.write("  # 左递归\n")
                    else:
                        f.write("\n")
            
            f.write("--------------------------------\n")
            dt = t1 - t0
            diag = tokenizer.diagnose()
            nlines = diag.end[0]
            f.write(f"总耗时: {dt:.3f} 秒; 共 {nlines} 行")
            if dt:
                f.write(f"; {nlines / dt:.0f} 行/s\n")
            else:
                f.write("\n")
            f.write("缓存大小:\n")
            f.write(f"  token array : {len(tokenizer._tokens):10}\n")
            f.write(f"        cache : {len(parser._cache):10}\n")
            
        print(f"日志已输出到 {log}")
    
def generate_python_code(filename, output, verbose=False):
    try:
        grammar, parser, tokenizer, gen = build_python_parser_and_generator(
            filename,
            output,
            verbose,
            verbose
        )
        return grammar, parser, tokenizer, gen
    except Exception as err:
        if verbose:
            raise
        traceback.print_exception(err.__class__, err, None)
        sys.stderr.write("使用 -v 参数查看完整错误跟踪信息\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
