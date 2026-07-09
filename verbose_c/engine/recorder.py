import os
import re
import time
from typing import Any

from verbose_c.error import VBCRuntimeError
from verbose_c.vm.memory import MemoryManager


def create_dump_path(filename: str) -> str:
    """根据源文件名生成 dumps 目录下的 markdown 路径。"""
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', filename)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs("dumps", exist_ok=True)
    return os.path.join("dumps", f"{safe_name}_{timestamp}.md")


def _escape_markdown_table_cell(value) -> str:
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", "<br>")


def format_parser_generation_markdown(report, heading_level: int = 2, include_details: bool = True) -> str:
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


def format_runtime_error(error: VBCRuntimeError) -> None:
    print("错误跟踪:")
    for frame in error.traceback:
        print(f'  在文件 "{frame.filepath}" 中, 第 {frame.line} 行, {frame.scope_name} 中:')
        for source in frame.source_line_context or []:
            print(f"    {source}")
    print(error.message)


class VmDebugLogCollector(list):
    """VM 调试日志收集器，写入时同步通知 recorder。"""

    def __init__(self, recorder: "PipelineRecorder"):
        super().__init__()
        self._recorder = recorder

    def append(self, item) -> None:
        super().append(item)
        self._recorder.on_vm_log(item)


class PipelineRecorder:
    """编译/运行流水线的控制台 log 与 markdown dump 输出。"""

    def __init__(
        self,
        *,
        source_filename: str,
        log_modules: set[str] | None = None,
        dump_modules: set[str] | None = None,
        dump_path: str | None = None,
        dump_title: str | None = None,
        basic_info_lines: list[str] | None = None,
    ):
        self.source_filename = source_filename
        self.dump_path = dump_path
        self._dump_title = dump_title or f"{source_filename} Verbose-C Dump"
        self._basic_info_lines = basic_info_lines or [f"- 源文件: `{source_filename}`"]
        self._started_at = time.strftime("%Y-%m-%d %H:%M:%S")

        log_modules = log_modules or set()
        dump_modules = dump_modules or set()
        self._log_all = "all" in log_modules
        self._log_compile = self._log_all or "compile" in log_modules
        self._log_vm = self._log_all or "vm" in log_modules
        self._log_parser = self._log_all or "parser" in log_modules

        dump_all = "all" in dump_modules
        self._dump_parser = dump_all or "parser" in dump_modules
        self._dump_preprocess = dump_all or "preprocess" in dump_modules
        self._dump_tokens = dump_all or "tokens" in dump_modules
        self._dump_ast = dump_all or "ast" in dump_modules
        self._dump_opcode = dump_all or "opcode" in dump_modules
        self._dump_ir = dump_all or "ir" in dump_modules
        self._dump_machine = dump_all or "machine" in dump_modules
        self._dump_optimize = dump_all or "optimize" in dump_modules
        self._dump_const = dump_all or "const" in dump_modules
        self._dump_label = dump_all or "label" in dump_modules
        self._dump_vm = dump_all or "vm" in dump_modules
        self._dump_memory = dump_all or "memory" in dump_modules

        self._toc_lines: list[str] = ["- [基本信息](#基本信息)"]
        self._section_body = ""
        self._vm_section_open = False
        self._error_recorded = False

        if self.dump_path:
            self._write_working_file()

    def log_compile_start(self) -> None:
        if self._log_compile:
            print(f"编译源代码文件: {self.source_filename}")

    def log_compile_engine(self) -> None:
        if self._log_compile:
            print("调用核心编译引擎...")

    def log_compile_done(self) -> None:
        if self._log_compile:
            print("编译完成。")

    def log_vm_start(self) -> None:
        if self._log_vm:
            print("\n执行字节码...\n")

    def log_vm_done(self) -> None:
        if self._log_vm:
            print("程序执行完成")

    def on_parser_generated(self, report) -> None:
        if self._log_parser:
            print(format_parser_generation_markdown(report, heading_level=2, include_details=False))
        if self._dump_parser and self.dump_path:
            self._append_section(
                "解析器生成",
                format_parser_generation_markdown(report, heading_level=2, include_details=True)
            )

    def on_raw_tokens(self, tokens) -> None:
        """dump 词法分析后、预处理前的 token 序列（--dump tokens）。"""
        if not self._dump_tokens or not self.dump_path:
            return
        title = "原始Token序列"
        self._append_section(title, self._format_tokens_section(tokens, title))

    def on_preprocessed_tokens(self, tokens) -> None:
        """dump 预处理后的 token 序列（--dump preprocess）。"""
        if not self._dump_preprocess or not self.dump_path:
            return
        title = "预处理Token序列"
        self._append_section(title, self._format_tokens_section(tokens, title))

    def on_ast(self, node) -> None:
        if not self._dump_ast or not self.dump_path:
            return
        from verbose_c.parser.parser.parser import ast_dump
        content = "## AST 结构\n\n```text\n"
        content += ast_dump(node, indent=4)
        content += "\n```\n\n"
        self._append_section("AST 结构", content)

    def on_compiled(self, output) -> None:
        if not self.dump_path:
            return
        if self._dump_opcode and output.bytecode and output.optimization_result:
            self._append_section("字节码", self._format_bytecode_section(output.optimization_result.original_bytecode))
        if self._dump_opcode and output.bytecode and not output.optimization_result:
            self._append_section("字节码", self._format_bytecode_section(output.bytecode))
        if self._dump_optimize and output.ast_optimization_result:
            self._append_section(
                "AST 优化",
                self._format_ast_optimization_section(output.ast_optimization_result, output.function_compilation_results),
            )
        if self._dump_optimize and output.optimization_result:
            self._append_section(
                "优化字节码",
                self._format_optimization_section(output.optimization_result, output.function_compilation_results),
            )
        if self._dump_const and output.constant_pool:
            self._append_section("常量池", self._format_constant_pool_section(output.constant_pool))
        if self._dump_label and output.labels and output.optimization_result:
            self._append_section("标签", self._format_labels_section(output.optimization_result.original_labels))
        if self._dump_label and output.labels and not output.optimization_result:
            self._append_section("标签", self._format_labels_section(output.labels))
        if self._dump_ir and output.ir_program:
            from verbose_c.compiler.ir import format_ir_program

            self._append_section("IR", format_ir_program(output.ir_program))
        if self._dump_machine and output.machine_program:
            from verbose_c.compiler.native import format_machine_program

            self._append_section("Machine IR", format_machine_program(output.machine_program))
        if self._dump_opcode and output.function_compilation_results:
            self._append_section("函数编译结果", self._format_function_results_section(output.function_compilation_results))

    def on_memory(self, memory) -> None:
        """dump 程序结束时刻的堆内存快照（--dump memory）。"""
        if not self._dump_memory or not self.dump_path:
            return
        self._append_section("内存快照", self._format_memory_section(memory))

    def on_vm_log(self, entry: str) -> None:
        if not self._dump_vm or not self.dump_path:
            return
        if not self._vm_section_open:
            self._vm_section_open = True
            self._append_section("虚拟机执行记录", "## 虚拟机执行记录\n\n```text\n", record_toc=True)
        with open(self.dump_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        self._section_body += entry + "\n"

    def on_error(self, error: Exception) -> None:
        if self._error_recorded:
            return
        self._error_recorded = True
        if isinstance(error, VBCRuntimeError):
            format_runtime_error(error)
        if not self.dump_path:
            return
        if self._vm_section_open:
            with open(self.dump_path, "a", encoding="utf-8") as f:
                f.write("```\n")
            self._section_body += "```\n"
            self._vm_section_open = False
        content = "## 错误信息\n\n```text\n"
        content += f"{type(error).__name__}: {error}\n"
        content += "```\n\n"
        self._append_section("错误信息", content)

    def finalize(self, success: bool) -> str | None:
        if not self.dump_path:
            return None
        if self._vm_section_open:
            self._section_body += "```\n"
            self._vm_section_open = False
        toc = "## 目录\n\n" + "\n".join(self._toc_lines) + "\n\n"
        basic_info = self._format_basic_info_section(success=success)
        with open(self.dump_path, "w", encoding="utf-8") as f:
            f.write(f"# {self._dump_title}\n\n")
            f.write(toc)
            f.write(basic_info)
            f.write(self._section_body)
        print(f"\n运行记录已保存到：{self.dump_path}")
        return self.dump_path

    def create_vm_log_collector(self) -> VmDebugLogCollector | None:
        if self._dump_vm and self.dump_path:
            return VmDebugLogCollector(self)
        return None

    def _format_basic_info_section(self, success: bool | None = None) -> str:
        lines = ["## 基本信息\n", "\n"]
        lines.extend(line + "\n" for line in self._basic_info_lines)
        lines.append(f"- 生成时间: `{self._started_at}`\n")
        if success is None:
            lines.append("- 编译结果: `进行中`\n\n")
        else:
            lines.append(f"- 编译结果: `{'成功' if success else '失败'}`\n\n")
        return "".join(lines)

    def _write_working_file(self) -> None:
        with open(self.dump_path, "w", encoding="utf-8") as f:
            f.write(f"# {self._dump_title}\n\n")
            f.write(self._format_basic_info_section(success=None))

    def _append_section(self, toc_title: str, content: str, record_toc: bool = True) -> None:
        if record_toc:
            self._toc_lines.append(f"- [{toc_title}](#{toc_title.lower().replace(' ', '-')})")
        self._section_body += content
        with open(self.dump_path, "a", encoding="utf-8") as f:
            f.write(content)

    def _format_tokens_section(self, tokens, title: str) -> str:
        lines = [
            f"## {title}\n\n",
            "| 序号 | TokenType | 字面量 | 行:列 | 文件 |\n",
            "| --- | --- | --- | --- | --- |\n",
        ]
        for index, token in enumerate(tokens):
            literal = repr(token.value)
            if token.is_keyword:
                literal = f"{literal} (keyword)"
            line_col = "-"
            if token.line is not None and token.column is not None:
                line_col = f"{token.line}:{token.column}"
            elif token.line is not None:
                line_col = str(token.line)
            filepath = token.path or "-"
            lines.append(
                f"| {index} | `{token.type.name}` | "
                f"`{_escape_markdown_table_cell(literal)}` | "
                f"{line_col} | `{_escape_markdown_table_cell(filepath)}` |\n"
            )
        lines.append("\n")
        return "".join(lines)

    def _format_memory_section(self, memory: MemoryManager) -> str:
        entries = memory.snapshot()
        lines = [
            "## 内存快照\n\n",
            f"- 堆对象数: `{len(entries)}`\n\n",
            "| 地址 | 类型 | 对象 |\n",
            "| --- | --- | --- |\n",
        ]
        for address, obj in entries:
            obj_type = getattr(obj, "_object_type", type(obj).__name__)
            type_name = obj_type.name if hasattr(obj_type, "name") else str(obj_type)
            obj_text = _escape_markdown_table_cell(repr(obj))
            lines.append(f"| {address} | `{type_name}` | `{obj_text}` |\n")
        lines.append("\n")
        return "".join(lines)

    def _format_bytecode_section(self, bytecode: list[tuple[Any, ...]]) -> str:
        lines = ["## 字节码\n\n", "| 索引 | 指令 |\n", "| --- | --- |\n"]
        for i, instruction in enumerate(bytecode):
            if len(instruction) == 1:
                lines.append(f"| {i} | `{instruction[0].name}` |\n")
            else:
                opcode_text = _escape_markdown_table_cell(f"{instruction[0].name} {instruction[1]!r}")
                lines.append(f"| {i} | `{opcode_text}` |\n")
        lines.append("\n")
        return "".join(lines)

    def _format_optimization_section(self, module_result, function_results: dict[str, Any]) -> str:
        lines = ["## 优化字节码\n\n"]
        lines.extend(self._format_optimized_bytecode_result("module", module_result, 3))
        for func_name, result in function_results.items():
            opt_result = result.get("optimization_result") if isinstance(result, dict) else None
            if opt_result:
                lines.extend(self._format_optimized_bytecode_result(func_name, opt_result, 3))
        return "".join(lines)

    def _format_optimized_bytecode_result(self, name: str, result: Any, heading_level: int) -> list[str]:
        heading = "#" * heading_level
        stats = result.stats
        lines = [f"{heading} `{_escape_markdown_table_cell(name)}`\n\n"]
        lines.extend([
            f"- 删除 NOP: `{stats.removed_nops}`\n",
            f"- 删除不可达指令: `{stats.removed_unreachable}`\n",
            f"- 删除无意义跳转: `{stats.removed_redundant_jumps}`\n",
            f"- 合并跳转链: `{stats.redirected_jumps}`\n",
            f"- 优化轮次: `{stats.passes}`\n\n",
        ])
        lines.extend(self._format_bytecode_table(result.optimized_bytecode))
        return lines

    def _format_bytecode_table(self, bytecode: list[tuple[Any, ...]]) -> list[str]:
        lines = ["| 索引 | 指令 |\n", "| --- | --- |\n"]
        for i, instruction in enumerate(bytecode):
            if len(instruction) == 1:
                lines.append(f"| {i} | `{instruction[0].name}` |\n")
            else:
                opcode_text = _escape_markdown_table_cell(f"{instruction[0].name} {instruction[1]!r}")
                lines.append(f"| {i} | `{opcode_text}` |\n")
        lines.append("\n")
        return lines

    def _format_ast_optimization_section(self, module_result, function_results: dict[str, Any]) -> str:
        lines = ["## AST 优化\n\n"]
        lines.extend(self._format_ast_optimization_result("module", module_result, 3))
        for func_name, result in function_results.items():
            opt_result = result.get("ast_optimization_result") if isinstance(result, dict) else None
            if opt_result:
                lines.extend(self._format_ast_optimization_result(func_name, opt_result, 3))
        return "".join(lines)

    def _format_ast_optimization_result(self, name: str, result: Any, heading_level: int) -> list[str]:
        heading = "#" * heading_level
        stats = result.stats
        lines = [
            f"{heading} `{_escape_markdown_table_cell(name)}`\n\n",
            f"- 常量折叠: `{stats.folded_constants}`\n",
            f"- 常量传播: `{stats.propagated_constants}`\n",
            f"- 拷贝传播: `{stats.propagated_copies}`\n",
            f"- 分支优化: `{stats.optimized_branches}`\n",
            f"- 公共子表达式消除: `{stats.eliminated_common_subexpressions}`\n",
            f"- 简单内联: `{stats.inlined_functions}`\n",
        ]
        if stats.skipped:
            lines.append("\n| 跳过原因 | 次数 |\n")
            lines.append("| --- | --- |\n")
            for reason, count in sorted(stats.skipped.items()):
                lines.append(f"| `{_escape_markdown_table_cell(reason)}` | {count} |\n")
        lines.append("\n")
        return lines

    def _format_constant_pool_section(self, constants: list[Any]) -> str:
        lines = ["## 常量池\n\n", "| 索引 | 值 |\n", "| --- | --- |\n"]
        for i, constant in enumerate(constants):
            constant_text = _escape_markdown_table_cell(repr(constant))
            lines.append(f"| {i} | `{constant_text}` |\n")
        lines.append("\n")
        return "".join(lines)

    def _format_labels_section(self, labels: dict[str, int]) -> str:
        lines = ["## 标签\n\n", "| 标签 | 位置 |\n", "| --- | --- |\n"]
        for lbl, pos in labels.items():
            lines.append(f"| `{lbl}` | {pos} |\n")
        lines.append("\n")
        return "".join(lines)

    def _format_function_results_section(self, function_results: dict[str, Any]) -> str:
        lines = ["## 函数编译结果\n\n"]
        for func_name, result in function_results.items():
            lines.append(f"### 函数 `{func_name}`\n\n")
            opt_result = result.get("optimization_result") if isinstance(result, dict) else None
            bytecode = opt_result.original_bytecode if opt_result else result.get("bytecode")
            labels = opt_result.original_labels if opt_result else result.get("labels")
            if bytecode:
                lines.append("#### 操作码\n\n")
                lines.append("| 索引 | 指令 |\n")
                lines.append("| --- | --- |\n")
                for i, instruction in enumerate(bytecode):
                    if len(instruction) == 1:
                        lines.append(f"| {i} | `{instruction[0].name}` |\n")
                    else:
                        opcode_text = _escape_markdown_table_cell(f"{instruction[0].name} {instruction[1]!r}")
                        lines.append(f"| {i} | `{opcode_text}` |\n")
                lines.append("\n")
            if result.get("constants"):
                lines.append("#### 常量池\n\n")
                lines.append("| 索引 | 值 |\n")
                lines.append("| --- | --- |\n")
                for i, constant in enumerate(result["constants"]):
                    constant_text = _escape_markdown_table_cell(repr(constant))
                    lines.append(f"| {i} | `{constant_text}` |\n")
                lines.append("\n")
            if labels:
                lines.append("#### 标签\n\n")
                lines.append("| 标签 | 位置 |\n")
                lines.append("| --- | --- |\n")
                for label, pos in labels.items():
                    lines.append(f"| `{label}` | {pos} |\n")
                lines.append("\n")
        return "".join(lines)
