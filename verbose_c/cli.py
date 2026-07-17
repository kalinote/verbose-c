import argparse
import json
import os
import subprocess
import sys
import time
from verbose_c.engine.engine import run_bytecode_file, run_parser_generation, run_source_file, grammar_file
from verbose_c.engine.native_exporter import NativeExportRequest, parse_native_export_kinds
from verbose_c.engine.recorder import create_dump_path


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="verbose-c",
        description="Verbose-C Compiler"
    )

    parser.add_argument("filename", help="需要编译、执行或校验的文件（.vbc 源代码、.vbb 字节码、.gram 语法文件、raw native bin、PE .text raw section 或最小 PE image）")
    parser.add_argument("--log", nargs="?", const="all", help="按模块输出命令行日志（模块: compile, vm, parser, all；默认 all）")
    parser.add_argument("--dump", nargs="?", const="all", help="导出执行过程日志，支持模块: parser, tokens, preprocess, ast, opcode, ir, machine, const, label, vm, memory, all；默认 all")
    parser.add_argument("--no-warn", help="静默编译告警输出", action="store_true")
    parser.add_argument("-cp", "--compile-parser", help="编译语法文件生成解析器", action="store_true")
    parser.add_argument("--compile-only", help="只编译不执行源代码", action="store_true")
    parser.add_argument("--run-native-memory", help="调试模式：从源码或 .vbb 生成 x64 机器码并在 Windows x64 可执行内存中运行 native 入口，打印返回值并作为进程退出码", action="store_true")
    parser.add_argument("--run-native-pe", help="调试模式：从源码或 .vbb 生成最小 PE32+ image 并通过 Windows loader 运行，打印返回值并作为进程退出码", action="store_true")
    parser.add_argument("--native-result", help="调试模式：将 native 调试执行入口的完整返回值写入指定文本文件")
    parser.add_argument("--native-zero-exit-code", help="调试模式：native 调试执行成功时进程退出码固定为 0，native 返回值仅打印或写入 --native-result", action="store_true")
    parser.add_argument("--emit", action="append", metavar="KINDS", help="统一导出 native 产物，可重复或逗号分隔：native-listing, native-bin, native-text-bin, native-pe, native-map, native-bundle")
    parser.add_argument("--emit-dir", help="统一 --emit 产物的可选输出目录；未指定时在入口文件目录创建带时间戳的输出目录")
    parser.add_argument("--check-native-map", help="调试模式：将 filename 作为 raw native bin，并用指定 JSON map 校验 schema、target、摘要和结构化机器码清单")
    parser.add_argument("--check-native-text-map", help="调试模式：将 filename 作为 PE .text raw section，并用指定 JSON map 校验补零 section 与机器码清单")
    parser.add_argument("--check-native-pe-map", help="调试模式：将 filename 作为最小 PE32+ image，并用指定 JSON map 校验 PE 头和 .text section")
    parser.add_argument("--run-native-pe-file", help="调试模式：将 filename 作为最小 PE32+ image，用指定 JSON map 校验后通过 Windows loader 运行入口")
    parser.add_argument("--run-native-bin-memory", help="调试模式：将 filename 作为 raw native bin，用指定 JSON map 校验后在 Windows x64 可执行内存中运行入口")
    parser.add_argument("--run-native-text-bin-memory", help="调试模式：将 filename 作为 PE .text raw section，用指定 JSON map 校验补零 section 后在 Windows x64 可执行内存中运行入口")
    parser.add_argument("-o", "--output", help="指定 .vbb 字节码产物输出路径")
    parser.add_argument("-rp", "--refresh-parser", help="重新生成解析器", action="store_true")
    parser.add_argument("-O", dest="optimize_level", type=int, default=0, choices=[0, 1], help="优化等级：-O0 或 -O1")
    return parser.parse_args()


def _parse_module_sets(args):
    log_modules = set()
    dump_modules = set()
    allowed_log_modules = {"compile", "vm", "parser", "all"}
    allowed_dump_modules = {"parser", "preprocess", "tokens", "ast", "opcode", "ir", "machine", "optimize", "const", "label", "vm", "memory", "all"}

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


def _load_native_bin_and_map(bin_path: str, map_path: str) -> tuple[bytes, dict]:
    """读取 native 二进制产物与 map JSON。"""
    if not os.path.exists(bin_path):
        raise FileNotFoundError(2, "No such file or directory", bin_path)
    if not os.path.exists(map_path):
        raise FileNotFoundError(2, "No such file or directory", map_path)
    with open(bin_path, "rb") as bin_file:
        code = bin_file.read()
    with open(map_path, "r", encoding="utf-8-sig") as map_file:
        metadata = json.load(map_file)
    return code, metadata


def _check_native_map_file(bin_path: str, map_path: str) -> int:
    """校验 raw native bin 与 map 文件一致。"""
    from verbose_c.compiler.native import NativeCodegenError, validate_native_code_map_bytes
    try:
        code, metadata = _load_native_bin_and_map(bin_path, map_path)
        validate_native_code_map_bytes(code, metadata)
    except FileNotFoundError as error:
        print(f"错误: 文件 '{error.filename or error.args[-1]}' 不存在")
        return 1
    except json.JSONDecodeError as error:
        print(f"native map 校验失败: JSON 解析失败: {error}")
        return 1
    except NativeCodegenError as error:
        print(f"native map 校验失败: {error}")
        return 1
    print(f"native map 校验通过: {bin_path} <-> {map_path}")
    return 0


def _check_native_text_map_file(text_bin_path: str, map_path: str) -> int:
    """校验补零后的 PE .text raw section 与 map 文件一致。"""
    from verbose_c.compiler.native import NativeCodegenError, validate_native_text_section_map_bytes
    try:
        text_raw, metadata = _load_native_bin_and_map(text_bin_path, map_path)
        validate_native_text_section_map_bytes(text_raw, metadata)
    except FileNotFoundError as error:
        print(f"错误: 文件 '{error.filename or error.args[-1]}' 不存在")
        return 1
    except json.JSONDecodeError as error:
        print(f"native .text map 校验失败: JSON 解析失败: {error}")
        return 1
    except NativeCodegenError as error:
        print(f"native .text map 校验失败: {error}")
        return 1
    print(f"native .text map 校验通过: {text_bin_path} <-> {map_path}")
    return 0


def _check_native_pe_map_file(pe_path: str, map_path: str) -> int:
    """校验最小 PE32+ image 与 map 文件一致。"""
    from verbose_c.compiler.native import NativeCodegenError, validate_native_pe_image_bytes
    try:
        pe_image, metadata = _load_native_bin_and_map(pe_path, map_path)
        validate_native_pe_image_bytes(pe_image, metadata)
    except FileNotFoundError as error:
        print(f"错误: 文件 '{error.filename or error.args[-1]}' 不存在")
        return 1
    except json.JSONDecodeError as error:
        print(f"native PE map 校验失败: JSON 解析失败: {error}")
        return 1
    except NativeCodegenError as error:
        print(f"native PE map 校验失败: {error}")
        return 1
    print(f"native PE map 校验通过: {pe_path} <-> {map_path}")
    return 0


def _run_native_pe_file(pe_path: str, map_path: str, native_result_path: str | None) -> tuple[bool, int]:
    """校验并运行最小 PE32+ image 文件。"""
    from verbose_c.compiler.native import NativeCodegenError, validate_native_pe_image_bytes
    from verbose_c.compiler.native.runner import can_run_native_memory
    try:
        pe_image, metadata = _load_native_bin_and_map(pe_path, map_path)
        validate_native_pe_image_bytes(pe_image, metadata)
        if not can_run_native_memory():
            raise NativeCodegenError("native PE 文件执行仅支持 Windows x64")
        result = int(subprocess.run([pe_path], check=False).returncode)
        if native_result_path is not None:
            result_dir = os.path.dirname(os.path.abspath(native_result_path))
            if result_dir:
                os.makedirs(result_dir, exist_ok=True)
            with open(native_result_path, "w", encoding="utf-8") as result_file:
                result_file.write(f"{result}\n")
        print(f"native PE 文件入口返回值: {result}")
        return True, result
    except FileNotFoundError as error:
        print(f"错误: 文件 '{error.filename or error.args[-1]}' 不存在")
        return False, 1
    except json.JSONDecodeError as error:
        print(f"native PE 文件执行失败: JSON 解析失败: {error}")
        return False, 1
    except NativeCodegenError as error:
        print(f"native PE 文件执行失败: {error}")
        return False, 1
    except OSError as error:
        print(f"native PE 文件执行失败: {error}")
        return False, 1


def _run_native_bin_memory_file(bin_path: str, map_path: str, native_result_path: str | None) -> tuple[bool, int]:
    """校验并内存执行 raw native bin。"""
    from verbose_c.compiler.native import NativeCodegenError, run_native_bytes_in_memory
    try:
        code, metadata = _load_native_bin_and_map(bin_path, map_path)
        result = run_native_bytes_in_memory(code, metadata)
        if native_result_path is not None:
            result_dir = os.path.dirname(os.path.abspath(native_result_path))
            if result_dir:
                os.makedirs(result_dir, exist_ok=True)
            with open(native_result_path, "w", encoding="utf-8") as result_file:
                result_file.write(f"{result}\n")
        print(f"native raw bin 入口返回值: {result}")
        return True, result
    except FileNotFoundError as error:
        print(f"错误: 文件 '{error.filename or error.args[-1]}' 不存在")
        return False, 1
    except json.JSONDecodeError as error:
        print(f"native raw bin 内存执行失败: JSON 解析失败: {error}")
        return False, 1
    except NativeCodegenError as error:
        print(f"native raw bin 内存执行失败: {error}")
        return False, 1


def _run_native_text_bin_memory_file(text_bin_path: str, map_path: str, native_result_path: str | None) -> tuple[bool, int]:
    """校验并内存执行补零后的 PE .text raw section。"""
    from verbose_c.compiler.native import NativeCodegenError, run_native_text_section_bytes_in_memory
    try:
        text_raw, metadata = _load_native_bin_and_map(text_bin_path, map_path)
        result = run_native_text_section_bytes_in_memory(text_raw, metadata)
        if native_result_path is not None:
            result_dir = os.path.dirname(os.path.abspath(native_result_path))
            if result_dir:
                os.makedirs(result_dir, exist_ok=True)
            with open(native_result_path, "w", encoding="utf-8") as result_file:
                result_file.write(f"{result}\n")
        print(f"native .text 入口返回值: {result}")
        return True, result
    except FileNotFoundError as error:
        print(f"错误: 文件 '{error.filename or error.args[-1]}' 不存在")
        return False, 1
    except json.JSONDecodeError as error:
        print(f"native .text 内存执行失败: JSON 解析失败: {error}")
        return False, 1
    except NativeCodegenError as error:
        print(f"native .text 内存执行失败: {error}")
        return False, 1


def main():
    """根据参数组织编译流程并分发到 engine 入口。"""
    args = parse_args()
    log_modules, dump_modules = _parse_module_sets(args)
    if log_modules is None:
        sys.exit(1)

    native_export_request = None
    emit_dir = None
    if args.emit is not None:
        try:
            entry_path = os.path.abspath(args.filename)
            entry_stem = os.path.splitext(os.path.basename(entry_path))[0]
            emit_dir = args.emit_dir or os.path.join(
                os.path.dirname(entry_path),
                f"{entry_stem}_emit_out_{time.strftime('%Y%m%d_%H%M%S')}",
            )
            native_export_request = NativeExportRequest.organized(
                args.filename,
                emit_dir,
                parse_native_export_kinds(args.emit),
            )
        except ValueError as error:
            print(f"错误: {error}")
            sys.exit(1)
    unified_emit_conflicts = [
        (args.emit, "--emit"),
    ]

    if not args.compile_parser and args.filename and not os.path.exists(args.filename):
        print(f"错误: 文件 '{args.filename}' 不存在")
        sys.exit(1)
    if args.check_native_map and args.check_native_text_map:
        print("错误: --check-native-map 不能与 --check-native-text-map 同时使用")
        sys.exit(1)
    if args.check_native_map and args.check_native_pe_map:
        print("错误: --check-native-map 不能与 --check-native-pe-map 同时使用")
        sys.exit(1)
    if args.check_native_text_map and args.check_native_pe_map:
        print("错误: --check-native-text-map 不能与 --check-native-pe-map 同时使用")
        sys.exit(1)
    if args.check_native_map:
        if args.compile_parser:
            print("错误: --compile-parser 不能与 --check-native-map 同时使用")
            sys.exit(1)
        check_conflicts = [
            (args.compile_only, "--compile-only"),
            (args.run_native_memory, "--run-native-memory"),
            (args.run_native_pe, "--run-native-pe"),
            (args.run_native_pe_file, "--run-native-pe-file"),
            (args.run_native_bin_memory, "--run-native-bin-memory"),
            (args.run_native_text_bin_memory, "--run-native-text-bin-memory"),
            (args.native_result, "--native-result"),
            (args.native_zero_exit_code, "--native-zero-exit-code"),
            (args.output, "-o/--output"),
            (args.refresh_parser, "-rp/--refresh-parser"),
        ] + unified_emit_conflicts
        for enabled, option_name in check_conflicts:
            if enabled:
                print(f"错误: {option_name} 不能与 --check-native-map 同时使用")
                sys.exit(1)
        sys.exit(_check_native_map_file(args.filename, args.check_native_map))
    if args.check_native_text_map:
        if args.compile_parser:
            print("错误: --compile-parser 不能与 --check-native-text-map 同时使用")
            sys.exit(1)
        check_text_conflicts = [
            (args.compile_only, "--compile-only"),
            (args.run_native_memory, "--run-native-memory"),
            (args.run_native_pe, "--run-native-pe"),
            (args.run_native_pe_file, "--run-native-pe-file"),
            (args.run_native_bin_memory, "--run-native-bin-memory"),
            (args.run_native_text_bin_memory, "--run-native-text-bin-memory"),
            (args.native_result, "--native-result"),
            (args.native_zero_exit_code, "--native-zero-exit-code"),
            (args.output, "-o/--output"),
            (args.refresh_parser, "-rp/--refresh-parser"),
        ] + unified_emit_conflicts
        for enabled, option_name in check_text_conflicts:
            if enabled:
                print(f"错误: {option_name} 不能与 --check-native-text-map 同时使用")
                sys.exit(1)
        sys.exit(_check_native_text_map_file(args.filename, args.check_native_text_map))
    if args.check_native_pe_map:
        if args.compile_parser:
            print("错误: --compile-parser 不能与 --check-native-pe-map 同时使用")
            sys.exit(1)
        check_pe_conflicts = [
            (args.compile_only, "--compile-only"),
            (args.run_native_memory, "--run-native-memory"),
            (args.run_native_pe, "--run-native-pe"),
            (args.run_native_pe_file, "--run-native-pe-file"),
            (args.run_native_bin_memory, "--run-native-bin-memory"),
            (args.run_native_text_bin_memory, "--run-native-text-bin-memory"),
            (args.native_result, "--native-result"),
            (args.native_zero_exit_code, "--native-zero-exit-code"),
            (args.output, "-o/--output"),
            (args.refresh_parser, "-rp/--refresh-parser"),
        ] + unified_emit_conflicts
        for enabled, option_name in check_pe_conflicts:
            if enabled:
                print(f"错误: {option_name} 不能与 --check-native-pe-map 同时使用")
                sys.exit(1)
        sys.exit(_check_native_pe_map_file(args.filename, args.check_native_pe_map))
    if args.run_native_pe_file:
        run_pe_file_conflicts = [
            (args.compile_only, "--compile-only"),
            (args.run_native_memory, "--run-native-memory"),
            (args.run_native_pe, "--run-native-pe"),
            (args.run_native_bin_memory, "--run-native-bin-memory"),
            (args.run_native_text_bin_memory, "--run-native-text-bin-memory"),
            (args.output, "-o/--output"),
            (args.refresh_parser, "-rp/--refresh-parser"),
        ] + unified_emit_conflicts
        if args.compile_parser:
            print("错误: --compile-parser 不能与 --run-native-pe-file 同时使用")
            sys.exit(1)
        for enabled, option_name in run_pe_file_conflicts:
            if enabled:
                print(f"错误: {option_name} 不能与 --run-native-pe-file 同时使用")
                sys.exit(1)
        success, exit_code = _run_native_pe_file(args.filename, args.run_native_pe_file, args.native_result)
        if success and args.native_zero_exit_code:
            sys.exit(0)
        sys.exit(exit_code)
    if args.run_native_bin_memory:
        run_bin_conflicts = [
            (args.compile_only, "--compile-only"),
            (args.run_native_memory, "--run-native-memory"),
            (args.run_native_pe, "--run-native-pe"),
            (args.run_native_pe_file, "--run-native-pe-file"),
            (args.run_native_text_bin_memory, "--run-native-text-bin-memory"),
            (args.output, "-o/--output"),
            (args.refresh_parser, "-rp/--refresh-parser"),
        ] + unified_emit_conflicts
        if args.compile_parser:
            print("错误: --compile-parser 不能与 --run-native-bin-memory 同时使用")
            sys.exit(1)
        for enabled, option_name in run_bin_conflicts:
            if enabled:
                print(f"错误: {option_name} 不能与 --run-native-bin-memory 同时使用")
                sys.exit(1)
        success, exit_code = _run_native_bin_memory_file(args.filename, args.run_native_bin_memory, args.native_result)
        if success and args.native_zero_exit_code:
            sys.exit(0)
        sys.exit(exit_code)
    if args.run_native_text_bin_memory:
        run_text_conflicts = [
            (args.compile_only, "--compile-only"),
            (args.run_native_memory, "--run-native-memory"),
            (args.run_native_pe, "--run-native-pe"),
            (args.run_native_pe_file, "--run-native-pe-file"),
            (args.output, "-o/--output"),
            (args.refresh_parser, "-rp/--refresh-parser"),
        ] + unified_emit_conflicts
        if args.compile_parser:
            print("错误: --compile-parser 不能与 --run-native-text-bin-memory 同时使用")
            sys.exit(1)
        for enabled, option_name in run_text_conflicts:
            if enabled:
                print(f"错误: {option_name} 不能与 --run-native-text-bin-memory 同时使用")
                sys.exit(1)
        success, exit_code = _run_native_text_bin_memory_file(args.filename, args.run_native_text_bin_memory, args.native_result)
        if success and args.native_zero_exit_code:
            sys.exit(0)
        sys.exit(exit_code)
    if args.compile_only and args.run_native_memory:
        print("错误: --compile-only 不能与 --run-native-memory 同时使用")
        sys.exit(1)
    if args.compile_only and args.run_native_pe:
        print("错误: --compile-only 不能与 --run-native-pe 同时使用")
        sys.exit(1)
    if args.compile_parser and args.run_native_memory:
        print("错误: --compile-parser 不能与 --run-native-memory 同时使用")
        sys.exit(1)
    if args.compile_parser and args.run_native_pe:
        print("错误: --compile-parser 不能与 --run-native-pe 同时使用")
        sys.exit(1)
    if args.run_native_memory and args.run_native_pe:
        print("错误: --run-native-memory 不能与 --run-native-pe 同时使用")
        sys.exit(1)
    if args.native_result and not (args.run_native_memory or args.run_native_pe or args.run_native_pe_file or args.run_native_bin_memory or args.run_native_text_bin_memory):
        print("错误: --native-result 必须与 --run-native-memory、--run-native-pe、--run-native-pe-file、--run-native-bin-memory 或 --run-native-text-bin-memory 同时使用")
        sys.exit(1)
    if args.native_zero_exit_code and not (args.run_native_memory or args.run_native_pe or args.run_native_pe_file or args.run_native_bin_memory or args.run_native_text_bin_memory):
        print("错误: --native-zero-exit-code 必须与 --run-native-memory、--run-native-pe、--run-native-pe-file、--run-native-bin-memory 或 --run-native-text-bin-memory 同时使用")
        sys.exit(1)
    if args.compile_parser and args.emit:
        print("错误: --compile-parser 不能与 --emit 同时使用")
        sys.exit(1)

    if args.compile_parser:
        dump_path = create_dump_path(grammar_file) if dump_modules else None
        run_parser_generation(
            log_modules=log_modules,
            dump_modules=dump_modules,
            dump_path=dump_path,
        )
        sys.exit(0)
    else:
        dump_path = create_dump_path(args.filename) if dump_modules else None
        ext = os.path.splitext(args.filename)[1].lower()
        if ext == ".vbb":
            if args.output:
                print("错误: .vbb 输入不支持 -o/--output")
                sys.exit(1)
            if args.compile_only:
                print("错误: .vbb 输入不支持 --compile-only")
                sys.exit(1)
            result = run_bytecode_file(
                filename=args.filename,
                log_modules=log_modules,
                dump_modules=dump_modules,
                dump_path=dump_path,
                run_native_memory=args.run_native_memory,
                run_native_pe=args.run_native_pe,
                native_result_path=args.native_result,
                native_export_request=native_export_request,
            )
        else:
            result = run_source_file(
                filename=args.filename,
                log_modules=log_modules,
                dump_modules=dump_modules,
                dump_path=dump_path,
                output_path=args.output,
                execute=not args.compile_only and not args.run_native_memory and not args.run_native_pe,
                refresh_parser=args.refresh_parser,
                show_warnings=not args.no_warn,
                optimize_level=args.optimize_level,
                run_native_memory=args.run_native_memory,
                run_native_pe=args.run_native_pe,
                native_result_path=args.native_result,
                native_export_request=native_export_request,
            )
        if args.run_native_memory and result.success:
            print(f"native 入口返回值: {result.exit_code}")
            if args.native_zero_exit_code:
                sys.exit(0)
        if args.run_native_pe and result.success:
            print(f"native PE 入口返回值: {result.exit_code}")
            if args.native_zero_exit_code:
                sys.exit(0)
        if args.emit and result.success and result.export_report is not None:
            print(f"native 产物已导出到: {emit_dir}")
            if result.export_report.manifest_path is not None:
                print(f"native manifest: {result.export_report.manifest_path}")
        sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
