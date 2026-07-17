# Verbose-C P2-4 实现复核与结构优化清单

本文档记录对 P2-4 x64 机器码后端 MVP 的实现复核结果，以及当前代码结构、重复逻辑和文档状态中需要继续处理的问题。

本文档的目标不是否定 P2-4 的完成状态，而是把已经出现的维护成本转化为可跟踪、可验收的后续任务。

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

复核时执行以下专项测试：

```powershell
.\.venv\Scripts\python.exe -m pytest `
    tests\test_native_codegen.py `
    tests\test_native_lowering.py `
    tests\test_ir_lowering.py -q
```

结果：`656 passed`。

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
- `lowering.py` 负责 IR 到 Machine IR。
- `runner.py` 负责执行前校验和 Windows 可执行内存调用。
- `pe_writer.py` 负责最小 PE image。
- `native_exporter.py` 负责统一导出、写后读回和 manifest。
- `recorder.py` 只记录结构化编译与导出报告。

主要问题集中在局部职责过载、重复校验、重复 CLI 分发和过度集中的测试文件。当前没有阻止 P2-4 验收的功能缺口，但继续扩展 P2-5 前应优先处理高风险结构问题。

## 2. 问题总览

| 编号 | 优先级 | 状态 | 问题 |
| --- | --- | --- | --- |
| FIXME-001 | 高 | 待处理 | 后端阶段捕获所有 `Exception`，可能掩盖内部缺陷 |
| FIXME-002 | 中 | 待处理 | P2-5 文档状态与现有最小 PE 实现冲突 |
| FIXME-003 | 中 | 待处理 | `codegen.py` 职责过载，文件和函数体量过大 |
| FIXME-004 | 中 | 待处理 | native 模块跨文件依赖私有符号并重复定义常量 |
| FIXME-005 | 中 | 待处理 | CLI 模式分发、冲突检测和结果处理重复 |
| FIXME-006 | 中 | 待处理 | 源码与 `.vbb` engine 执行流程重复且行为已分叉 |
| FIXME-007 | 低 | 待处理 | native exporter 对 `.text` 和 PE 做重复校验 |
| FIXME-008 | 低 | 待处理 | native codegen 测试文件过度集中 |
| FIXME-009 | 低 | 待处理 | P2-4 状态文档过长且包含大量实现级细节 |

## 3. 详细问题

### FIXME-001：后端阶段不应捕获所有异常

**优先级：高**

**涉及文件：**

- `verbose_c/engine/engine.py`
- `_populate_backend_outputs()`

**当前情况：**

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

**涉及文件：**

- `docs/FEATURE_IMPLEMENTATION_TARGETS.md`
- `verbose_c/compiler/native/pe_writer.py`
- `verbose_c/engine/engine.py`

**当前情况：**

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

**建议方案：**

把 P2-5 标记为“部分完成”，并明确拆成两层：

```text
已完成：调试用最小 PE32+，单 .text、无导入、无 runtime
未完成：.rdata、导入表、正式重定位、runtime ABI、堆、字符串、I/O、完整独立 AOT
```

**验收标准：**

- P2-4 和 P2-5 不再对同一能力给出相反状态。
- 文档明确“可由 loader 运行”和“生产级独立可执行文件”之间的边界。
- P2-5 验收项只保留尚未完成的 runtime 和完整 PE/COFF 能力。

### FIXME-003：拆分职责过载的 `codegen.py`

**优先级：中**

**涉及文件：**

- `verbose_c/compiler/native/codegen.py`

**当前情况：**

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

**优先级：中**

**涉及文件：**

- `verbose_c/compiler/native/codegen.py`
- `verbose_c/compiler/native/runner.py`
- `verbose_c/compiler/native/pe_writer.py`

**当前情况：**

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

`main()` 约 248 行，分别处理：

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

**涉及文件：**

- `verbose_c/engine/engine.py`
- `run_source_file()`
- `run_bytecode_file()`

**当前情况：**

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

**涉及文件：**

- `tests/test_native_codegen.py`

**当前情况：**

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

**涉及文件：**

- `docs/FEATURE_IMPLEMENTATION_TARGETS.md`

**当前情况：**

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

**验收标准：**

- P2-4 状态可以在一屏内快速判断完成度和边界。
- 字段级实现细节有独立、可定位的设计文档。
- P2-4 和 P2-5 不重复描述同一实现。

## 4. 推荐实施顺序

### 第一阶段：修正可靠性和状态偏差

1. 处理 FIXME-001，收紧后端异常捕获。
2. 处理 FIXME-002，修正 P2-5 当前状态。
3. 为 `.vbb` 缺失错误路径补测试，作为 FIXME-006 的最小前置修复。

这一阶段应保持机器码、map 和 CLI 接口不变。

### 第二阶段：建立清晰模块边界

1. 从 `codegen.py` 移出 Native Code 数据模型。
2. 移出 listing formatter。
3. 移出 map 构建和 validator。
4. 统一 rel32 描述和类型兼容规则。
5. 清除 runner、PE writer 对 codegen 私有符号的依赖。

每次只移动一种职责，并运行完整 native 专项测试。

### 第三阶段：收敛调用入口

1. 重构 CLI 文件型 native 模式表。
2. 统一 native 返回值文件写入。
3. 抽取源码和 `.vbb` 的共享 backend 执行阶段。
4. 删除 exporter 重复校验。

### 第四阶段：降低维护成本

1. 拆分 `tests/test_native_codegen.py`。
2. 精简 P2-4 状态正文。
3. 新增 native backend、map 和 PE 设计文档。

## 5. 重构约束

处理上述问题时应遵循以下约束：

- 不改变 P2-4 当前支持的语言子集。
- 不改变现有 x64 机器码字节，除非任务明确要求修复编码错误。
- 不改变 native map schema，除非单独提升 schema version。
- 不删除写后读回、自检和负向校验能力。
- 不把产物写入职责移回 `PipelineRecorder`。
- `NativeArtifactExporter` 继续负责导出和校验，recorder 只消费结构化报告。
- 不在结构重构中顺带实现 P2-5 runtime、导入表或完整 PE/COFF。
- 每一步都应运行 native 专项测试；影响 CLI 或 engine 时运行完整测试。

## 6. 完成判定

本清单可在满足以下条件后关闭：

- `_populate_backend_outputs()` 不再吞掉非预期内部异常。
- P2-5 文档准确描述最小 PE 已完成、正式 runtime/AOT 未完成。
- `codegen.py` 不再承载 model、map validator 和 listing formatter 的全部职责。
- native 模块不再跨文件导入私有符号。
- rel32 和类型兼容规则只有一个定义源。
- CLI native 文件模式使用统一冲突检查和分发结构。
- 源码与 `.vbb` 共用后端执行、导出和错误收尾流程。
- exporter 不再重复执行相同 validator。
- native 测试按职责拆分，测试数量和覆盖不下降。
- P2-4 状态文档恢复为简洁的目标和验收清单。
- native 专项测试和完整测试套件全部通过。
