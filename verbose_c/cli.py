import argparse
import os
from verbose_c.engine.engine import run_parser_generation, run_source_file, grammar_file
from verbose_c.engine.recorder import create_dump_path


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )

    parser.add_argument("filename", help="需要编译的文件（.vbc源代码文件或.gram语法文件）")
    parser.add_argument("--log", nargs="?", const="all", help="按模块输出命令行日志（模块: compile, vm, parser, all；默认 all）")
    parser.add_argument("--dump", nargs="?", const="all", help="导出执行过程日志，支持模块: parser, tokens, preprocess, ast, opcode, const, label, vm, all；默认 all")
    parser.add_argument("--no-warn", help="静默编译告警输出", action="store_true")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    parser.add_argument("--compile-only", help="只编译不执行源代码", action="store_true")
    parser.add_argument("-rp", "--refresh-parser", help="重新生成解析器", action="store_true")
    return parser.parse_args()


def _parse_module_sets(args):
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
            return None, None

    if args.dump is not None:
        dump_modules = {module.strip().lower() for module in args.dump.split(",") if module.strip()}
        if not dump_modules:
            dump_modules = {"all"}
        invalid_dump = sorted(dump_modules - allowed_dump_modules)
        if invalid_dump:
            print(f"错误: --dump 存在不支持的模块: {', '.join(invalid_dump)}")
            return None, None

    return log_modules, dump_modules


def main():
    """根据参数组织编译流程并分发到 engine 入口。"""
    args = parse_args()
    log_modules, dump_modules = _parse_module_sets(args)
    if log_modules is None:
        return

    if not args.compile_parser and args.filename and not os.path.exists(args.filename):
        print(f"错误: 文件 '{args.filename}' 不存在")
        return

    if args.compile_parser:
        dump_path = create_dump_path(grammar_file) if dump_modules else None
        run_parser_generation(
            log_modules=log_modules,
            dump_modules=dump_modules,
            dump_path=dump_path,
        )
    else:
        dump_path = create_dump_path(args.filename) if dump_modules else None
        run_source_file(
            filename=args.filename,
            log_modules=log_modules,
            dump_modules=dump_modules,
            dump_path=dump_path,
            execute=not args.compile_only,
            refresh_parser=args.refresh_parser,
            show_warnings=not args.no_warn,
        )


if __name__ == "__main__":
    main()
