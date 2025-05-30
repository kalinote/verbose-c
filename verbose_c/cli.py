import argparse
import os
import sys
import time
import traceback
from verbose_c.parser.ppg.build import build_python_parser_and_generator
from verbose_c.parser.ppg.validator import validate_grammar
from verbose_c.parser.lexer.lexer import Lexer

def parse_args():
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )
    
    # TODO 临时测试使用，后续完善
    parser.add_argument("filename", help="需要编译的语法文件")
    parser.add_argument("-o", "--output", help="输出文件名")
    parser.add_argument("-v", "--verbose", help="显示详细信息", action="store_true")
    parser.add_argument("-l", "--log", help="记录编译过程")
    parser.add_argument("-t", "--tokenization", help="仅计算文件 token", action="store_true")
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
    
    compile_file(args.filename, args.output, args.verbose, args.log)
    
def compile_file(filename, output, verbose, log=None):
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
