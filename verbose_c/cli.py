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
    parser.add_argument("--log", help="记录编译过程")
    parser.add_argument("-t", "--tokenization", help="输出token序列", action="store_true")
    parser.add_argument("-a", "--ast", help="输出AST", action="store_true")
    parser.add_argument("--opcode", help="输出操作码", action="store_true")
    parser.add_argument("-c", "--const", help="输出常量池", action="store_true")
    parser.add_argument("-l", "--label", help="输出标签", action="store_true")
    parser.add_argument("-oa", "--out-all", help="输出所有内容（token, AST, 操作码, 常量池, 标签）", action="store_true")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    
    if args.filename:
        if not os.path.exists(args.filename):
            print(f"错误: 文件 '{args.filename}' 不存在")
            return
    
    if args.tokenization:
        # Tokenization only supported for source files
        from verbose_c.parser.lexer.lexer import Lexer
        with open(args.filename, "r", encoding="utf-8") as f:
            source = f.read()
        lexer = Lexer(args.filename, source)
        tokens = list(lexer.tokenize())
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                for token in tokens:
                    f.write(f"{token}\n")
            print(f"Token序列已输出到: {args.output}")
        else:
            for token in tokens:
                print(token)
        return
    
    # Default behavior: compile source code
    if args.compile_parser:
        # Compile grammar file to generate parser
        compile_file(args.filename, args.output, args.verbose, args.log)
    else:
        # Compile source file to opcode
        compile_source_file(
            filename=args.filename,
            output=args.output,
            verbose=args.verbose,
            tokenization=args.tokenization or args.out_all,
            ast=args.ast or args.out_all,
            opcode=args.opcode or args.out_all,
            const=args.const or args.out_all,
            label=args.label or args.out_all
        )
        
def compile_source_file(
        filename, 
        output=None,
        verbose=False,
        tokenization=False,
        ast=False,
        opcode=False,
        const=False,
        label=False
    ):
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
        ast_node = parser.start()
        
        if ast_node is None:
            print("错误: 解析失败")
            return
            
        if verbose or ast:
            from verbose_c.parser.parser.parser import ast_dump
            ast_content = ast_dump(ast_node, indent=4)
            if verbose:
                print("\nAST结构:")
                print(ast_content)
            
        # 创建符号表
        symbol_table = SymbolTable(ScopeType.GLOBAL)
        
        # 生成操作码
        print("生成操作码...")
        opcode_gen = OpcodeGenerator(symbol_table)
        opcode_gen.visit(ast_node)
        
        # 输出结果到终端
        if verbose:
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
            
        # 如果指定了输出文件，写入内容
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                f.write("# Verbose-C 编译日志\n")
                f.write(f"# 源文件: {filename}\n")
                f.write("# 生成时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
                
                # 输出token序列
                if tokenization:
                    f.write("\n=== Token序列 ===\n")
                    for token in tokenizer.tokens:
                        f.write(f"{token}\n")
                
                # 输出AST结构
                if ast:
                    f.write("\n=== AST结构 ===\n")
                    f.write(ast_content)
                    f.write("\n")
                
                # 输出操作码
                if opcode:
                    f.write("\n=== 操作码 ===\n")
                    for i, instruction in enumerate(opcode_gen.bytecode):
                        if len(instruction) == 1:
                            f.write(f"{i:4d}: {instruction[0].name}\n")
                        else:
                            f.write(f"{i:4d}: {instruction[0].name} {instruction[1]}\n")
                
                # 输出常量池
                if const:
                    f.write(f"\n=== 常量池 ===\n")
                    for i, constant in enumerate(opcode_gen.constant_pool):
                        f.write(f"{i:4d}: {constant!r}\n")
                
                # 输出标签
                if label:
                    f.write(f"\n=== 标签 ===\n")
                    for label, pos in opcode_gen.labels.items():
                        f.write(f"{label}: {pos}\n")
            
            print(f"\n编译输出已保存到: {output}")
            
    except Exception as e:
        print(f"编译过程中发生错误: {e}")
        if verbose:
            traceback.print_exc()


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
