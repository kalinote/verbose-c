import argparse
import os
from tokenizer.lexer import Lexer

def parse_args():
    parser = argparse.ArgumentParser(description="Verbose-C Compiler")
    parser.add_argument("filename", help="需要编译的文件")
    return parser.parse_args()


def main():
    args = parse_args()
    
    if args.filename:
        if not os.path.exists(args.filename):
            print(f"错误: 文件 '{args.filename}' 不存在")
            return
        
        compile_file(args.filename)


def compile_file(filename):
    with open(filename, "r") as f:
        source = f.read()
    lexer = Lexer(filename, source)
    tokens = list(lexer.tokenize())

    for token in tokens:
        print(token)

if __name__ == "__main__":
    main()
