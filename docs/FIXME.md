# Verbose-C 实现复核与待修复清单

本文档保留 P2-4 x64 机器码后端 MVP 的复核历史，并跟踪当前的行为缺陷、结构问题和文档工作。状态核对日期：2026-09-21。

问题总览和每项最新处理结果代表当前状态。“原有情况”和历史建议仅解释任务来源；不能据此判断功能仍未实现。P2-4 和 P2-5 的稳定子集已完成，不代表所有语言边界均已闭环。

## 1. 当前结论

### 1.1 P2-4 完成状态

按照 [FEATURE_IMPLEMENTATION_TARGETS.md](./FEATURE_IMPLEMENTATION_TARGETS.md) 当前定义的目标和验收口径，P2-4 可以继续标记为“已完成”。

当前已经跑通以下闭环：

```text
.vbc 源码或 .vbb 字节码
  -> IR
  -> Machine IR
  -> Windows x64 机器码
  -> 可执行内存或调试用最小 PE
  -> native 入口返回值
```

目前还已完成正式 `--emit-exe`：输出自带字符串/标准 I/O 运行时、基址重定位及错误诊断的独立 Windows x64 exe，支持定长局部/全局标量数组及有界借用传参。范围见 [P2-5](./FEATURE_IMPLEMENTATION_TARGETS.md) 和 [README](../README.md)。

以下为 P2-4 专项测试入口，在项目根目录执行：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
.\.venv\Scripts\python.exe -m pytest `
    tests\test_native_codegen.py `
    tests\test_native_lowering.py `
    tests\test_ir_lowering.py -q -p no:cacheprovider
```

早期复核记录为 `656 passed`，不是当前测试总量。新增的 map、数值语义、左值、数组、I/O 和 AOT 等测试已有独立模块；当前全量验收使用 `.\scripts\verify.ps1`，以本次生成的 JUnit 报告为准。

### 1.2 P2-4 能力对照

| P2-4 目标 | 当前状态 | 主要实现位置 |
| --- | --- | --- |
| `.vbc/.vbb -> IR -> Machine IR -> x64` | 已完成 | `compiler/ir`、`compiler/native/lowering.py`、`compiler/native/codegen.py` |
| 极小 x64 指令编码器 | 已完成 | `compiler/native/encoder.py` |
| Machine IR 指令选择 | 已完成 | `compiler/native/codegen.py` |
| 保守栈槽分配 | 已完成 | `compiler/native/codegen.py`、`compiler/native/abi.py` |
| 整数、布尔、分支、循环和函数调用 | 已完成 | `compiler/native/lowering.py`、`compiler/native/codegen.py` |
| 递归、栈参数和受限全局标量 | 已完成 | `compiler/native/codegen.py` |
| listing、map、raw bin 和统一导出 | 已完成 | `engine/native_exporter.py` |
| Windows x64 可执行内存运行 | 已完成 | `compiler/native/runner.py` |
| 调试用最小 PE 写出与执行 | 已完成 | `compiler/native/pe_writer.py`、`engine/engine.py` |
| 不支持能力明确报错 | 已完成 | `NativeLoweringError`、`NativeCodegenError` 及负向测试 |
| dump 和结构化验收信息 | 已完成 | `compiler/native/codegen.py`、`engine/recorder.py` |

### 1.3 总体结构评价

当前高层分层基本合理：

- `encoder.py` 负责 x64 字节编码。
- `machine_ir.py` 负责 Machine IR 数据结构。
- `model.py`、`listing_formatter.py`、`map_format.py` 分别负责 Native Code 模型、listing 和 map。
- `lowering.py` 负责 IR 到 Machine IR。
- `runner.py` 负责执行前校验和 Windows 可执行内存调用。
- `pe_writer.py` / `pe_layout.py` 负责 PE 写出与布局；`runtime.py` 提供原生运行时，`relocations.py` 共享重定位定义。
- `native_exporter.py` 负责统一导出、写后读回和 manifest。
- `recorder.py` 只记录结构化编译与导出报告。

结构问题主要集中在局部职责过载、重复校验、重复 CLI 分发和仍然过大的测试文件。P2-5 已有正式 AOT 实现；继续扩展时应同时处理下面记录的行为缺陷和剩余维护问题。

## 2. 问题总览

| 编号 | 优先级 | 状态 | 问题 |
| --- | --- | --- | --- |
| FIXME-001 | 高 | 已处理 | 仅降级已知后端错误，内部异常进入失败及 traceback 通路 |
| FIXME-002 | 中 | 已处理 | P2-5 稳定 AOT 子集已完成，已区分调试 PE、正式 runtime 与对象模型扩展 |
| FIXME-003 | 中 | 首阶段已处理 | 已拆出模型、listing 和 map；指令选择、静态分析及大校验函数的进一步拆分可后续进行 |
| FIXME-004 | 中 | 已处理 | 模型、ABI 规则及 rel32 共享定义公开复用，runner 不再依赖 codegen 私有函数 |
| FIXME-005 | 中 | 待处理 | CLI 模式分发、冲突检测和结果处理重复 |
| FIXME-006 | 中 | 已处理 | 源码与 `.vbb` engine 执行流程已统一，错误路径分叉已修复 |
| FIXME-007 | 低 | 待处理 | native exporter 对 `.text` 和 PE 做重复校验 |
| FIXME-008 | 低 | 部分处理 | map 等测试已有独立模块，native codegen 剩余测试仍较集中 |
| FIXME-009 | 低 | 部分处理 | P2-4 状态正文已精简，独立 native 设计文档仍待补充 |
| FIXME-010 | 高 | 待处理 | 预处理逻辑条件短路时未消费右侧 token，合法条件会编译失败 |
| FIXME-011 | 中 | 待处理 | `bool main()` 的 VM/native 退出码不一致 |

## 3. 详细问题

### FIXME-001：后端阶段不应捕获所有异常

**处理结果（2026-09-16）：** IR、Machine IR 和 codegen 分别只捕获 `IRLoweringError`、`NativeLoweringError`、`NativeCodegenError`。内部异常透传到 engine 的失败诊断；`tests/test_engine_execution.py` 覆盖源码、字节码、dump 和强制 native 路径的异常注入。以下保留原问题说明。

**优先级：高**

**涉及文件：**

- `verbose_c/engine/engine.py`
- `_populate_backend_outputs()`

**原有情况（已修复）：**

IR lowering、Machine IR lowering 和 native codegen 三个阶段均使用 `except Exception`。当当前请求不强制要求对应后端产物时，异常会被写入 `ir_error`、`machine_error` 或 `native_code_error`，普通 VM 编译继续成功。

**风险：**

- `NativeCodegenError` 等已知“不支持”错误可以被降级记录，这是预期行为。
- `NameError`、`AttributeError`、`TypeError` 等编程缺陷也会被同样降级。
- 没有请求 dump 时，内部错误可能完全不被用户看到。
- CI 可能出现 VM 测试全部通过，但 native 后端已经损坏的情况。

**建议方案：**

1. IR 阶段只捕获明确的 IR lowering 错误类型。
2. Machine IR 阶段只捕获 `NativeLoweringError`。
3. native codegen 阶段只捕获 `NativeCodegenError`。
4. 其他异常继续抛出，由 engine 的内部错误通路处理并输出 traceback。
5. 增加测试，确认一个人为注入的 `RuntimeError` 不会被误当成“不支持”。

**验收标准：**

- 已知不支持能力仍可在普通 VM 路径下降级记录。
- 内部异常不会被写入后端错误字段后静默吞掉。
- `--dump ir`、`--dump machine` 和 native 强制执行的错误行为保持一致。
- 现有 VM、IR 和 native 测试全部通过。

### FIXME-002：修正 P2-5 状态与最小 PE 实现的冲突

**优先级：中**

**状态：已处理（2026-07-17）**

**最新状态（2026-09-21）：** 正式 AOT、运行时、字符串、标准 I/O、DIR64 重定位、局部/全局标量数组及借用引用已实现。剩余范围是数组返回及地址逃逸、一般指针、结构体/类对象和逐对象回收。下面“部分完成”的拆分方案保留为 7 月复核历史。

**涉及文件：**

- `docs/FEATURE_IMPLEMENTATION_TARGETS.md`
- `verbose_c/compiler/native/pe_writer.py`
- `verbose_c/engine/engine.py`

**原有情况：**

P2-4 已经具备：

- 固定 DOS header。
- PE signature 和 COFF header。
- PE32+ OptionalHeader。
- 单 `.text` section。
- 入口 RVA/VA。
- 最小 PE 文件写出和读回校验。
- Windows loader 进程执行。

但 P2-5 当前仍写着“无 PE/COFF 写出器”和“不能生成操作系统可加载 `.exe`”。这与 `pe_writer.py`、`--emit native-pe`、`--run-native-pe` 和相关测试不一致。

**风险：**

- 项目状态看起来比真实实现落后。
- P2-5 后续任务无法区分已经完成的最小 PE 和尚未完成的正式 AOT/runtime。
- 后续贡献者可能重复实现已经存在的 PE header 和 `.text` 写出逻辑。

**历史建议方案：**

把 P2-5 标记为“部分完成”，并明确拆成两层：

```text
已完成：调试用最小 PE32+，单 .text、无导入、无 runtime
未完成：.rdata、导入表、正式重定位、runtime ABI、堆、字符串、I/O、完整独立 AOT
```

**当时实施结果（2026-07-17，现状以上述最新状态为准）：**

- `FEATURE_IMPLEMENTATION_TARGETS.md` 的主线路线图已将 P2-5 从“未完成”改为“部分完成”。
- P2-5 已明确记录固定 DOS header、PE/COFF header、PE32+ Optional Header、单 `.text`、入口写出、map 校验和 Windows loader 执行为已完成能力。
- `.rdata`、导入表、基址重定位、native runtime ABI、堆、字符串、I/O 和正式 AOT 入口继续保留为未完成项。
- P2-4 只把最小 PE 作为跨阶段调试验证入口引用，不再与 P2-5 对同一 PE 写出能力给出相反状态。
- 顶部主线路线图和文末能力现状表已同步为同一状态口径。

**验收标准：**

- P2-4 和 P2-5 不再对同一能力给出相反状态。
- 文档明确“可由 loader 运行”和“生产级独立可执行文件”之间的边界。
- P2-5 明确列出已完成的正式 runtime/PE 能力及尚未完成的对象模型扩展。

### FIXME-003：拆分职责过载的 `codegen.py`

**首阶段结果（2026-09-16）：** 已迁出 `model.py`、`listing_formatter.py`、`map_format.py`，并以 `pe_layout.py`、`relocations.py` 共享常量；旧公共导入继续兼容。169 个 map 测试函数迁至 `tests/test_native_map.py`。迁移前后 50 个样例各自 O0/O1 的机器码、map、listing 和 PE 摘要完全一致。生成上下文和静态分析仍保留原模块，大 map 校验函数的细分留待后续。以下保留原问题和长期拆分建议。

**优先级：中**

**涉及文件：**

- `verbose_c/compiler/native/codegen.py`

**首次复核情况（首阶段拆分前）：**

复核时 `codegen.py` 约 5581 行、98 个函数或方法，同时包含：

- Native Code 数据模型。
- Machine IR 结构校验。
- 静态常量传播和危险运算分析。
- 指令选择和机器码生成。
- rel32 回填。
- listing 格式化。
- native map 生成。
- native map/schema 校验。
- `.text` map 校验。

其中 `validate_native_code_map_bytes()` 单个函数约 2141 行。

**风险：**

- 任意 schema 变更都可能影响 codegen、formatter、runner 和 PE writer。
- 单元测试难以按职责定位。
- 模块导入方向不清晰，runner 和 PE writer 被迫依赖 codegen。
- 超长函数难以审查遗漏字段、重复校验和错误分支。

**建议模块结构：**

```text
verbose_c/compiler/native/
  model.py                 NativeCodeProgram 等数据结构
  codegen.py               Machine IR -> NativeCodeProgram
  instruction_selector.py  指令选择与栈槽装载/写回
  program_validator.py     NativeCodeProgram 内存结构校验
  map_format.py            map 构建、schema 和字节一致性校验
  listing_formatter.py     教学 listing 输出
  relocations.py           rel32 常量、解析和修补校验
```

不要求一次拆完。建议先移动纯数据结构和纯格式化/校验函数，保持行为不变，再拆生成上下文。

**验收标准：**

- `codegen.py` 只负责机器码生成主流程。
- runner、PE writer 不再从 `codegen.py` 导入私有函数。
- map validator 有独立测试文件。
- 拆分过程中机器码字节、map JSON 和 listing 快照不发生非预期变化。

### FIXME-004：消除私有跨模块依赖和重复 rel32 定义

**处理结果（2026-09-16）：** 类型兼容规则位于 `abi.py`，符号/栈槽描述位于 `model.py`，rel32 指令长度、opcode、助记符前缀统一位于 `relocations.py`；runner 和 PE writer 直接消费公开模型及 map 接口，不再依赖 codegen 的私有函数。以下保留原问题说明。

**优先级：中**

**涉及文件：**

- `verbose_c/compiler/native/codegen.py`
- `verbose_c/compiler/native/runner.py`
- `verbose_c/compiler/native/pe_writer.py`

**原有情况（已修复）：**

`runner.py` 从 `codegen.py` 导入 `_is_argument_type_compatible`、`_native_program_symbols` 等私有函数。`pe_writer.py` 也从 `codegen.py` 导入 map validator。

rel32 jump opcode 和伪汇编前缀表同时存在于 codegen 和 runner 中。

**风险：**

- 私有函数改名会跨模块破坏 runner。
- 新增 `jcc` 时可能只更新 codegen 或 runner 其中一处。
- runner 的执行前校验和 map 校验可能出现不同规则。

**建议方案：**

- 把类型兼容规则迁入公开的 `native/type_rules.py` 或 validation 模块。
- 把符号表归一化逻辑迁入 Native Code model 层。
- 把 rel32 kind、opcode、指令长度和 asm 前缀定义成一个共享描述表。
- codegen、runner、map validator 都消费同一份描述。

**验收标准：**

- native 模块之间不存在以下形式的导入：`from ... import _private_name`。
- rel32 opcode 数据只有一个定义源。
- 新增或删除一种 relocation 时只需修改一份描述表。

### FIXME-005：收敛 CLI 模式分发和冲突检测

**优先级：中**

**涉及文件：**

- `verbose_c/cli.py`

**当前情况：**

`main()` 仍分别处理：

- raw bin map 校验。
- `.text` map 校验。
- PE map 校验。
- PE 文件执行。
- raw bin 内存执行。
- `.text` 内存执行。
- 源码、`.vbb`、parser 生成模式。

这些分支重复维护冲突选项列表、错误提示、结果文件写入和退出码处理。native 返回值文件写入逻辑在 CLI 和 engine 中也重复存在。

**风险：**

- 增加一个 CLI 参数时需要修改多份冲突表。
- 不同模式可能漏掉互斥选项。
- 相同错误在不同入口产生不同文本或退出码。

**建议方案：**

定义结构化模式描述，例如：

```python
mode = {
    "name": "--check-native-map",
    "enabled": args.check_native_map,
    "conflicts": (...),
    "handler": _check_native_map_file,
}
```

再由统一流程完成：

1. 识别当前文件型 native 模式。
2. 校验只能启用一个模式。
3. 校验公共冲突集合。
4. 调用 handler。
5. 统一处理返回值文件和零退出码。

结果文件写入应抽到 engine 或一个共享 I/O helper，CLI 不重复实现。

**验收标准：**

- `main()` 主要负责参数解析和模式分派。
- 文件型 native 模式共用一套冲突检查。
- `native_result_path` 只有一个写入实现。
- 所有现有 CLI 互斥和错误信息测试继续通过。

### FIXME-006：统一源码与 `.vbb` 的后端执行阶段

**优先级：中**

**状态：已处理（2026-07-17）**

**涉及文件：**

- `verbose_c/engine/engine.py`
- `run_source_file()`
- `run_bytecode_file()`

**原有情况：**

两个入口在获得 `CompilerOutput` 后重复完成：

- backend 补全。
- native 内存执行。
- native PE 执行。
- native 产物导出。
- recorder 通知。
- VM 执行。
- 异常转换。
- recorder finalize。
- `RunResult` 组装。

重复代码已经出现行为分叉：源码路径会在 `VBCCompileError.filepath` 为空时补上入口文件名，`.vbb` 路径直接打印 `e.filepath`，可能输出“编译错误: 文件 None”。

**实施结果：**

- `run_source_file()` 与 `run_bytecode_file()` 保持公开签名不变，统一委托 `_run_file_pipeline()`。
- 源码编译、增量缓存和 `.vbb` 加载仍保留各自入口逻辑；获得 `CompilerOutput` 后共用 backend 要求计算、native/VM 执行、导出、异常转换、recorder 收尾和 `RunResult` 组装。
- `.vbb` 后端错误缺少路径时优先使用内嵌源码路径，加载阶段失败则回退到 `.vbb` 输入路径；两条路径共用警告处理。
- 显式 IR dump 在源码与 `.vbb` 路径上均要求 IR lowering 成功，Machine IR dump 继续保持宽容策略。
- `tests/test_engine_execution.py` 覆盖错误路径、警告、IR required 标志和 recorder 单次收尾。

**建议方案：**

保留两个入口各自的加载阶段：

```text
run_source_file   -> 编译或增量缓存 -> CompilerOutput
run_bytecode_file -> 加载 .vbb      -> CompilerOutput
```

然后进入共享函数：

```text
_run_compilation_output(
    compilation_output,
    source_path,
    native options,
    export request,
    recorder,
)
```

异常格式化和 `RunResult` finalization 也应共享。

**验收标准：**

- 源码和 `.vbb` native 执行、导出、dump 行为一致。
- 两条路径的错误路径和警告处理一致。
- `.vbb` 后端错误不会显示 `filepath=None`。
- engine 现有公开函数签名保持稳定，除非单独安排 API 调整。

### FIXME-007：删除 native exporter 的确定性重复校验

**优先级：低**

**涉及文件：**

- `verbose_c/engine/native_exporter.py`
- `NativeArtifactExporter.export()`

**当前情况：**

写出 `.text` 或 PE 后已经使用当前 metadata 校验一次。当同次还导出 map 时，又对相同字节和相同 metadata 执行一次相同 validator。

第一次校验通过后，第二次校验没有新的输入，因此不会增加有效覆盖，只会增加执行时间和分支数量。

**建议方案：**

- `.text` 写出后只调用一次 `validate_native_text_section_map_bytes()`。
- PE 写出后只调用一次 `validate_native_pe_image_bytes()`。
- raw bin 仅在 map 存在时调用 `validate_native_code_map_bytes()`。
- 保留写后读回字节一致性检查。

**验收标准：**

- 每个二进制产物只执行一次结构化 validator。
- raw bin、`.text`、PE 和 map 的交叉错误测试继续通过。
- 导出报告和 manifest 内容不变。

### FIXME-008：拆分超大的 native codegen 测试文件

**优先级：低**

**最新状态（2026-09-21）：部分处理。** 2026-09-16 已将 map 测试迁入 `tests/test_native_map.py`；数值语义、左值、数组、I/O 和 AOT 也已有独立测试模块。`tests/test_native_codegen.py` 仍混合保留编码器、codegen、runner、PE、exporter 和 CLI 用例，进一步拆分尚未完成。

**涉及文件：**

- `tests/test_native_codegen.py`

**首次复核情况（拆分前）：**

复核时该文件约 17871 行、567 个测试函数，覆盖编码器、codegen、map、runner、PE、exporter 和 CLI。

**风险：**

- 测试职责边界不清晰。
- 查找失败用例和相关 fixture 成本高。
- 重构某个模块时无法快速识别对应测试集合。
- 多人修改时冲突概率高。

**建议拆分：**

```text
tests/native/
  test_encoder.py
  test_codegen.py
  test_codegen_validation.py
  test_native_map.py
  test_native_runner.py
  test_pe_writer.py
  test_native_exporter.py
  test_native_cli.py
```

首轮只移动测试，不修改断言和 fixture 行为。

**验收标准：**

- 原测试数量和参数化 case 数量不减少。
- 每个测试模块可以独立运行。
- 公共构造器和 fixture 放入 `tests/native/conftest.py` 或专用 helper。
- 拆分前后专项测试结果一致。

### FIXME-009：精简 P2-4 状态文档

**优先级：低**

**状态：部分处理（2026-07-17）**

**涉及文件：**

- `docs/FEATURE_IMPLEMENTATION_TARGETS.md`

**原有情况：**

P2-4 状态中混入大量字段级 schema、地址计算、SHA-256、负向测试和 runner 前置校验细节。部分单行超过 1000 字符，最长接近 4000 字符。

**风险：**

- 功能目标和实现细节混在一起。
- 小幅代码变更需要同步修改超长状态段落。
- P2-4 与 P2-5 的边界更难阅读。
- 重复描述测试内容，容易和测试代码漂移。

**建议方案：**

`FEATURE_IMPLEMENTATION_TARGETS.md` 只保留：

- 目标能力。
- 完成状态。
- 支持和不支持边界。
- 验收入口。
- 指向详细设计文档的链接。

把 map schema、PE 字段、runner 校验规则迁移到独立文档，例如：

```text
docs/NATIVE_BACKEND.md
docs/NATIVE_MAP_FORMAT.md
docs/NATIVE_PE_MVP.md
```

**实施结果：**

- `FEATURE_IMPLEMENTATION_TARGETS.md` 的 P2-4 正文已收敛为完成状态、目标能力、支持边界和验收入口四类信息。
- P2-4 已从实现日志式长段落精简为状态与验收说明，不再枚举 map schema、PE 字段、地址推导、SHA-256 和负向测试 case。
- 调试用最小 PE 的完成状态统一归入 P2-5，P2-4 仅保留跨阶段引用，两个目标不再重复维护同一实现清单。
- 尚无独立的 `NATIVE_BACKEND.md`、`NATIVE_MAP_FORMAT.md` 或 `NATIVE_PE_MVP.md`；README、目标清单和模块关系图已有当前概览，字段级独立设计文档仍为剩余工作。

**验收标准：**

- P2-4 状态可以在一屏内快速判断完成度和边界。
- 字段级实现细节有独立、可定位的设计文档。
- P2-4 和 P2-5 不重复描述同一实现。

### FIXME-010：预处理条件的短路解析不完整

**优先级：高；状态：待处理（2026-09-21 复现）。**

**涉及文件：** `verbose_c/preprocessor/const_expr.py` 的 `_evaluate_expr_tokens()`。

`parse_or()` / `parse_and()` 直接用 Python 的 `or` / `and` 连接递归解析调用。左侧已决定真值时，右侧解析被跳过，游标停留在尚未消费的 token；`#if 1 || 0`、`#if 0 && 1` 均报“无法解析的 token”，而不是选择正确分支。

**待修复与验收：** 区分语法消费与短路求值，保证表达式完整解析；覆盖真值组合、嵌套括号、`defined()` 和宏展开后的条件。完整预处理常量表达式和未定义标识符转为 `0` 仍按 C-P0-3 跟踪。

### FIXME-011：`bool main()` 的 VM/native 退出码不一致

**优先级：中；状态：待处理（2026-09-21 复现）。**

**涉及文件：** `verbose_c/compiler/opcode_generator_visitor.py`、`verbose_c/vm/core.py` 和原生入口返回路径。

自动入口允许 `BoolType`，但 VM 的 `SET_EXIT_CODE` 仅提取 `VBCInteger`，其他对象设为 `0`。`bool main() { return true; }` 在 VM 返回 `0`，Windows x64 native 内存执行返回 `1`，两条路径均正常执行成功。

**待修复与验收：** 统一布尔入口是否支持及其退出码语义，并覆盖 O0/O1、源码/字节码和 VM/native/AOT。当前文档将稳定入口限定为 `int main()` / `void main()`。

## 4. 剩余工作的推荐顺序

1. 修复 FIXME-010 的预处理逻辑条件解析，统一 FIXME-011 的布尔入口语义。
2. 处理 FIXME-005：收敛 CLI 模式冲突检查、分发和返回值文件写入。
3. 处理 FIXME-007：删除相同输入上的重复 exporter 校验，保留写后读回与结构校验。
4. 按实际维护需要推进 FIXME-003 的剩余拆分及 FIXME-008 的测试整理。
5. 补充 FIXME-009 的字段级 native 设计说明。

FIXME-001、002、004、006 和 FIXME-003 的首阶段已完成，不再列入待办。类构造链、实例转型和其他语言扩展继续由功能目标清单跟踪。

## 5. 重构约束

处理上述问题时应遵循以下约束：

- 纯结构重构保持当前 VM/native 支持的语言子集不变；行为修复单独定义预期并验证。
- 不改变现有 x64 机器码字节，除非任务明确要求修复编码错误。
- 不改变 native map schema，除非单独提升 schema version。
- 不删除写后读回、自检和负向校验能力。
- 不把产物写入职责移回 `PipelineRecorder`。
- `NativeArtifactExporter` 继续负责导出和校验，recorder 只消费结构化报告。
- 不在结构重构中顺带扩展对象运行时或改变已实现的 AOT、导入与重定位约定。
- 每一步都应运行 native 专项测试；影响 CLI 或 engine 时运行完整测试。

## 6. 完成判定

本清单可在满足以下条件后关闭：

- `_populate_backend_outputs()` 不再吞掉非预期内部异常。
- P2-5 文档准确描述正式 runtime/AOT、定长局部/全局标量数组及借用引用已完成，数组地址逃逸、一般指针和对象模型仍待扩展。
- `codegen.py` 不再承载 model、map validator 和 listing formatter 的全部职责。
- native 模块不再跨文件导入私有符号。
- rel32 和类型兼容规则只有一个定义源。
- CLI native 文件模式使用统一冲突检查和分发结构。
- 源码与 `.vbb` 共用后端执行、导出和错误收尾流程。
- exporter 不再重复执行相同 validator。
- native 测试按职责拆分，测试数量和覆盖不下降。
- P2-4 状态文档恢复为简洁的目标和验收清单。
- 预处理逻辑条件正确消费 token 并选择分支，布尔入口有一致的跨后端约定。
- native 专项测试和完整测试套件全部通过。
