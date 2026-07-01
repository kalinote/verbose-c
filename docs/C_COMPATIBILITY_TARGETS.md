# Verbose-C C语言兼容目标清单

本文档只包含“兼容 C 语言本体”的目标，不包含类、继承、`new/super`、范围语法、关键字参数等扩展功能。

## 1. 目标边界

- 目标：优先把 `verbose-c` 提升到“可运行且行为接近 C 语言”的实现。
- 范围：语法、类型语义、预处理、运行时行为、标准库接口（最小可用集）。
- 非目标：任何非 C 原生特性（面向对象扩展、脚本化语法糖等）。

## 2. 兼容级别定义

- **P0（必须）**：缺失会直接导致常见 C 代码无法编译或行为明显错误。
- **P1（高优）**：不阻断最小闭环，但会严重影响 C 代码迁移体验。
- **P2（增强）**：兼容度提升项，建议在 P0/P1 稳定后推进。

---

## 3. P0 目标（必须完成）

### P0-1 Token 化预处理器与编译管线重构

- 目标能力：
  - 【已完成】将预处理移动到词法分析之后：源码先转换为 Token，再执行预处理
  - 【已完成】`#define` 不再做直接文本替换，而是定义、匹配、展开 Token 序列（`MacroDefinition.replacement` 存 token 列表）
  - 【已完成】预处理器只分析有意义的 Token，避免误替换字符串、注释、标识符子串等文本片段
  - 【已完成】词法分析器产出 `MACRO_CODE` 等可供预处理器使用的 Token，并保留宏指令、换行和必要空白边界
  - 【已完成】编译管线支持 `source -> tokens -> preprocess tokens -> parser`，不再依赖 `source -> preprocess text -> tokens`
  - 【方案变更】【已完成】`#include` 在 `Preprocessor.process_tokens` 内递归处理（读文件 → `Tokenizer` → 递归 `process_tokens` → splice），而非在 engine 层逐文件调度
  - 【方案变更】【已完成】Token `path` 在 `Lexer`/`Tokenizer` 入口及 `_clone_token` 时统一规范为绝对路径
- 当前现状：
  - 【已完成】`process_tokens` 已实现 `#define`、`#include "..."` 与 token 级宏展开
  - 【已完成】`process()` 文本路径已移除，仅保留 `process_tokens`
  - 【已完成】`--dump tokens` 输出预处理前 token；`--dump preprocess` 输出预处理后 token
  - 【方案变更】【已完成】dump 分「预处理前 / 预处理后」两节 token 表格，不再输出预处理源码文本
  - 【已完成】多文件源码由 `SourceManager`（`verbose_c/fs`）按 path 统一缓存；`get_line_source(path, line)` 支持 include 文件取行
  - 【待完善】`#include` 为简化实现，与 C17 6.10.2 存在差异（见 P1-6）
  - 【已完成】C17 预定义宏内置：`__FILE__`、`__LINE__`、`__DATE__`、`__TIME__`、`__STDC__`、`__STDC_VERSION__`（201710）、`__STDC_HOSTED__`、`__STDC_UTF_16__`、`__STDC_UTF_32__`；`__func__` 在编译器阶段作为预定义标识符支持
- 验收标准：
  - 【已完成】普通宏、函数式宏和 `#include "..."` 处理均基于 Token 序列完成
  - 【已完成】`#define A 1` 不会误替换 `DATA`、字符串字面量或注释中的 `A`
  - 【已完成】预处理后的 Token 能直接进入 parser，编译管线无需重新从文本做词法分析
  - 【已完成】调试 dump 可分别展示预处理前、预处理后的 Token 序列
  - 【已完成】`tests/grammar_preprocessor_test.vbc` 预处理测试通过
  - 【已完成】include 文件 token 的解析错误可输出对应文件的源码上下文
  - 【已完成】新增 Token 边界相关回归测试（`tests/grammar/preprocessor_token_boundary_test.vbc`：字符串内宏名、标识符子串、注释、函数式宏无括号等专用用例）



### P0-2 Token 宏展开语义闭环

- 目标能力：
  - 【已完成】基于 Token 序列实现普通宏、函数式宏、嵌套宏展开
  - 【已完成】用宏展开排除表（hiding 集）替代固定递归次数作为主防护机制
  - 【已完成】展开结果 rescan 时可继续匹配其他宏；当前展开链中的宏名不可再展开
  - 【已完成】`MAX_EXPANSION_DEPTH` 保留为兜底保护
  - 【待完善】字符串化（`#`）、拼接（`##`）等复杂宏能力（扩展点已预留，未实现）
- 当前现状：
  - 【已完成】`_expand_at` / `_rescan` / `_consume_token` 实现 token 级展开与嵌套 rescan
  - 【已完成】函数宏仅在后跟 `(` 时展开；形参替换为实参 token 序列后再 rescan
  - 【已完成】反斜杠续行 `#define` 在注册时合并宏体并 tokenize
  - 【已完成】C17 预定义宏：`__FILE__`/`__LINE__` 按宏调用点动态展开（经用户宏传递时保留调用点行号）；其余在预处理器初始化时注册
- 验收标准：
  - 【待完善】`#define A A`、`#define A B` + `#define B A` 等循环宏有专用回归测试（hiding 已实现，缺用例）
  - 【已完成】`#define A B` + `#define B 1` 可继续展开为最终值（`grammar_preprocessor_test.vbc` 覆盖）
  - 【已完成】复杂宏样例（如 `BUILD_TOTAL(START_VALUE)`、include 导入宏）可稳定得到预期展开结果
  - 【已完成】`tests/grammar/predefined_macros_test.vbc` 覆盖预定义宏与 `__func__`



### P0-3 预处理条件编译

- 目标能力：
  - 【未完成】支持 `#if/#ifdef/#ifndef/#elif/#else/#endif`
  - 【未完成】支持 `defined(MACRO)` 基本判断
- 当前现状：
  - 【未完成】条件宏未实现；未识别预处理指令仅 warn 并跳过
- 验收标准：
  - 【未完成】带条件编译分支的示例代码可稳定编译且分支选择正确
  - 【未完成】嵌套条件编译可正常解析
  - 【未完成】非法宏块能给出明确错误信息（包含文件和行号）



### P0-4 C 条件判断语义修正

- 目标能力：
  - `if/while/for` 条件允许标量类型（至少整数与指针）
  - 逻辑非 `!` 支持整数/指针
- 当前现状：
  - 当前实现偏严格布尔类型判断，不符合 C 习惯
- 验收标准：
  - `if (1)`, `if (ptr)`, `while (n)` 均可编译并行为正确
  - `!0`、`!1`、`!ptr` 结果符合 C 预期



### P0-5 基础运算符闭环（C 高频基础子集）

- 目标能力：
  - 取模：`%`
  - 复合赋值：`+= -= *= /= %=`
  - 自增自减：`++` `--`（前置/后置）
- 当前现状：
  - 词法有较多 token，语法与后端未闭环
- 验收标准：
  - 每个运算符至少有独立用例覆盖
  - 运算优先级与结合性符合 C 常识
  - 与赋值语句、循环更新表达式组合使用行为正确



### P0-6 函数声明原型（Prototype）

- 目标能力：
  - 支持“先声明，后定义”与跨模块调用基础语义
- 当前现状：
  - 主要是函数定义形式，缺少纯声明路径
- 验收标准：
  - `int add(int, int);` + 后续定义可通过
  - 调用时参数检查遵循原型



### P0-7 数组与下标访问

- 目标能力：
  - 一维数组声明、初始化、读写访问
  - 表达式中数组下标求值
- 当前现状：
  - 词法有 `[` `]`，语法/语义/后端未闭环
- 验收标准：
  - `int arr[3]; arr[0]=1;` 可编译运行
  - 读写下标结果正确
  - 越界行为至少有一致策略（报错或定义明确）



### P0-8 C 控制流补齐：`switch/case/default`

- 目标能力：
  - 支持 `switch`、`case`、`default`、`break` 语义
  - 支持 case 穿透（fallthrough）
- 当前现状：
  - 语法层未包含该语句族
- 验收标准：
  - 可编译执行多分支 `switch` 示例
  - 无 `break` 时能够按 C 语义穿透
  - 默认分支行为正确



### P0-9 关键数据结构基础：`typedef` / `enum` / `struct`

- 目标能力：
  - 支持 `typedef` 类型别名
  - 支持 `enum` 枚举常量
  - 支持结构体定义、变量声明、成员访问（`.` 与 `->`）
- 当前现状：
  - 语法与类型系统尚未形成这些结构的主路径
- 验收标准：
  - typedef 可用于变量声明/函数参数
  - enum 常量可参与表达式
  - 结构体字段读写正确

---



## 4. P1 目标（高优先级）



### P1-1 指针语义增强

- 目标能力：
  - 指针算术：`ptr + n`、`ptr - n`、`ptr1 - ptr2`
  - `&` 作用于更完整左值场景（不仅变量名）
- 验收标准：
  - 数组与指针联动场景可运行
  - 指针运算结果与元素步长语义一致



### P1-2 类型转换与整数提升规则完善

- 目标能力：
  - 完善算术转换、比较转换、显式强转规则
  - 修正整数除法行为与 C 语义一致
- 验收标准：
  - 典型整型/浮点混算结果正确
  - `int/int` 除法结果符合 C 语义
  - 非法转换给出明确错误



### P1-3 `sizeof` 与更完整声明语法

- 目标能力：
  - `sizeof(type)` 与 `sizeof(expr)`
  - 更接近 C 的声明器语法（复杂指针声明）
- 验收标准：
  - 常见 `sizeof` 场景结果正确
  - 与数组、指针、结构体组合使用时结果一致



### P1-4 作用域与存储期关键字（最小集）

- 目标能力：
  - `const`、`static`（至少函数内静态变量与文件级静态）
- 验收标准：
  - `const` 变量禁止非法修改
  - `static` 生命周期与可见性符合预期



### P1-5 标准库最小可迁移接口（libc 最小子集）

- 目标能力：
  - 在现有 I/O 基础上，补齐常用 C 风格接口映射（可分阶段）
  - 至少保证常见输入输出与字符串基础能力可迁移
- 验收标准：
  - 迁移小型 C 示例（输入输出+字符串处理）无需大改



### P1-6 `#include` 与 C17 6.10.2 对齐

- 目标能力：
  - 区分 `#include "file.h"` 与 `#include <file.h>` 的搜索路径
  - 支持编译器 `-I` 及系统 include 目录
  - 允许同一头文件被多次 include，重复防护交由 `#ifndef` / `#pragma once`（配合 P0-3 条件编译）
  - include 目标不存在时输出编译错误而非 warn + 丢弃
- P0 已实现（简化行为）：
  - 仅 `#include "path/file"` 双引号形式
  - 搜索路径：`dirname(当前源文件) / filename`
  - `_included_files` 绝对路径去重，循环 include 时 warn + 跳过（等同隐式 `#pragma once`）
  - 找不到文件：warn + 丢弃该预处理指令
  - 插入时机与宏可见性与 C 标准一致
- 与 C 标准差异：


| 行为            | C17 6.10.2          | P0 实现          |
| ------------- | ------------------- | -------------- |
| `"file.h"` 搜索 | 当前目录 → 再按 `<>` 规则重搜 | 仅当前文件相对目录      |
| `<file.h>`    | system/include 目录   | 不支持（warn + 跳过） |
| 重复 include    | 允许，靠守卫防重复           | 路径去重跳过         |
| 循环 include    | 无内置防护               | 检测环并跳过         |
| 找不到文件         | diagnostic（通常错误）    | warn + 丢弃      |


- 验收标准：
  - `#include <stdio.h>` 可通过 `-I` 或系统路径解析
  - 无 include guard 的头文件被 include 两次时，内容出现两次（与 C 一致）
  - 找不到 include 文件时编译失败并给出文件与行号



### P1-7 统一错误诊断与输出（`verbose_c/error`）

- 背景与动机：
  - 当前错误/警告输出分散在 `engine.py`、`recorder.py`、`error_collector.py`、`preprocessor.py`、`type_checker_visitor.py`、`vm/core.py` 等模块，格式不统一
  - 终端与 dump 文案不一致：解析错误有较完整报告，dump 中仅 `{ExceptionType}: {message}` 一行摘要
  - `VBCCompileError.message` 为平铺字符串，`engine` 用 `split('\n')` 逐行打印，难以实现树形层级展示
  - 验收原则（§8）要求错误含文件、行号、核心原因；需统一格式化层支撑
- 设计原则：
  - **采集与展示分离**：各阶段只负责产生结构化信息；`verbose_c/error` 只负责「长什么样、怎么输出」
  - **Dump 格式化进 error 包，文件 I/O 留在 recorder**：`error` 提供 `format_dump_section(error) -> str`，`PipelineRecorder.on_error` 负责何时写入 markdown
  - **不迁入 error 包的内容**：解析/类型检查/VM 的错误采集逻辑；PPG 语法文件工具链；CLI 参数校验；`opcode_generator` 内部 `RuntimeError`（编译器 bug）
- 目标包结构（`verbose_c/error/`）：

```
verbose_c/error/
  exceptions.py    # 已有：VBCError / VBCCompileError / VBCRuntimeError / TracebackFrame
  report.py        # 【待实现】结构化报告数据（ParseErrorReport、Diagnostic 等）
  format.py        # 【待实现】CLI 树形 / 纯文本 / dump markdown 格式化
  __init__.py      # 导出公开 API
```

- 当前各阶段错误/警告分布（基线）：


| 阶段   | 产生位置                          | 载体                                   | 格式化                             | 终端输出                               |
| ---- | ----------------------------- | ------------------------------------ | ------------------------------- | ---------------------------------- |
| CLI  | `cli.py`                      | 无                                    | 无                               | `cli.py` 直接 `print`                |
| 词法   | `lexer.py`                    | `SyntaxError`                        | 无                               | `engine` `except Exception`        |
| 预处理  | `preprocessor.py`             | 警告字符串                                | `_warn` 内拼位置                    | `preprocessor._warn` 直接 `print`    |
| 语法解析 | `error_collector.py`          | `ParseError` 列表                      | `format_error_report()`         | 包进 `VBCCompileError` 后 `engine` 打印 |
| 类型检查 | `type_checker_visitor.py`     | `list[str]`                          | `"\n".join(errors)`             | `VBCCompileError` → `engine`       |
| 代码生成 | `opcode_generator_visitor.py` | `RuntimeError` 等                     | 无                               | 内部错误 / traceback                   |
| 编译编排 | `engine.py`                   | `VBCCompileError`                    | 无                               | `split('\n')` 循环 `print`           |
| 运行时  | `vm/core.py`                  | `VBCRuntimeError` + `TracebackFrame` | `recorder.format_runtime_error` | `recorder.on_error` **内 print**    |
| Dump | `recorder.on_error`           | 任意 `Exception`                       | 仅类型名 + `str(error)`             | 写入 markdown                        |


- 实施步骤：



#### 步骤 1（必须）：解析错误树形 CLI 输出 + `VBCCompileError` 统一格式化

- 【未完成】新建 `verbose_c/error/format.py`，实现树形渲染（`├─` / `└─` / `│` / `─`）
- 【未完成】`error_collector` 产出结构化 `ParseErrorReport`（或 formatter 可消费的 section 列表），去掉 `"\n错误上下文:"` 等嵌在字符串里的换行
- 【未完成】`Parser.get_error_report()` 返回结构化数据或委托 `error.format.format_parse_report(...)`
- 【未完成】`engine.compile_module` 抛出 `VBCCompileError` 时携带结构化报告，而非仅平铺 `message` 字符串
- 【未完成】`engine.run_source_file` 对 `VBCCompileError` 改为调用 `error.format.print_compile_error(e)`，删除 `split('\n')` 打印循环
- 【未完成】`recorder.on_error` 对 `VBCCompileError` 复用同一 formatter 写入 dump「错误信息」节
- CLI 树形示例（目标效果）：

```text
编译错误: 文件 <entry.vbc>
 ├─ 在文件 <entry.vbc> 中解析失败:
 ├─ 错误位置: 第 N 行，第 M 列，位于 <included.inc> 文件
 ├─ 错误: 期望 ... 其中之一, 实际是 '...'
 │
 ├─ 错误上下文:
 │    L | <source line>
 │         ^^^
 │
 └─ 语法解析规则调用栈:
     start -> ... -> expect
```

- 回归用例：【已有】`tests/error_report_test.vbc` + `tests/error_report_bad.inc`（include 文件内语法错误）



#### 步骤 2（必须）：运行时错误格式化迁入 `error` 包

- 【未完成】将 `recorder.format_runtime_error` 迁至 `verbose_c/error/format.py`
- 【未完成】`engine.run_source_file` 对 `VBCRuntimeError` 显式调用 formatter 打印（不再由 `recorder.on_error` 副作用打印）
- 【未完成】`recorder.on_error` 对 `VBCRuntimeError` 复用 formatter 写 dump
- 【待完善】`vm/core.py` 中 `TracebackFrame.source_line_context` 改用 `SourceManager` 取多行上下文（当前为单行 strip）



#### 步骤 3（必须）：类型检查错误接入统一 formatter

- 【未完成】`compiler.py` 抛出 `VBCCompileError` 前，将 `type_checker.errors` 转为与解析错误兼容的 section 列表
- 【未完成】类型检查多条错误时，树形输出每条为 `├─`，最后一条为 `└─`
- 【未完成】dump 与终端共用同一格式化路径



#### 步骤 4（高优）：警告输出统一

- 【未完成】新建 `format_warning(message, path?, line?)` 或 `Diagnostic(severity=warning)`
- 【未完成】`Preprocessor._warn` 改为只构造 diagnostic，不直接 `print`；由 `engine` 或统一 `ErrorSink` 输出（兼容 `--no-warn`）
- 【未完成】类型检查 `warnings` 与预处理警告使用同一警告格式



#### 步骤 5（可选）：结构化 Diagnostic 模型

- 【未完成】定义 `Diagnostic`：`severity`、`filepath`、`line`、`column`、`code`、`message`、`context_lines`、`rule_stack` 等
- 【未完成】`type_checker_visitor` 从 `errors.append(f"...")` 改为 `diagnostics.append(Diagnostic(...))`
- 【未完成】解析、类型、运行时均产出 `Diagnostic`，formatter 只消费 `list[Diagnostic]`
- 收益：多文件/多错误排序、国际化、IDE 集成、稳定错误码



#### 步骤 6（可选）：词法错误纳入 `VBCCompileError`

- 【未完成】`lexer.py` 非法字符等不再抛裸 `SyntaxError`，改为 `VBCCompileError` 或 `Diagnostic`
- 【未完成】经统一 formatter 输出，与解析错误样式一致



#### 步骤 7（可选）：Dump 错误节增强

- 【未完成】dump「错误信息」节输出完整树形/结构化报告（与终端一致），而非仅 `VBCCompileError: ...` 摘要
- 【未完成】运行时 dump 包含完整调用栈与源码上下文块
- 文件写入仍由 `PipelineRecorder` 编排，`error` 包只返回字符串



#### 步骤 8（可选，暂不纳入）：不在本计划范围

- `opcode_generator_visitor` 内部 `RuntimeError`（编译器实现缺陷，保留 Python traceback）
- PPG 语法文件生成链路（`validator.py`、`build.py`）的错误格式
- CLI 参数错误（足够简单，可保持 `cli.py` 内 `print`）
- 验收标准：
  - 【未完成】`tests/error_report_test.vbc` 终端输出为树形格式，且指向 include 文件的正确源码行
  - 【未完成】`--dump` 时「错误信息」节与终端报告内容一致（允许 markdown 代码块包裹）
  - 【未完成】类型检查失败时多条错误有统一树形/列表格式
  - 【未完成】`VBCRuntimeError` 打印职责不在 `recorder` 内隐式副作用，而经 `engine` + `error.format` 显式调用
  - 【待完善】反向样例测试覆盖：解析错误、类型错误、运行时错误各至少 1 个专用 `.vbc` 用例

---



## 5. P2 目标（增强项）



### P2-1 多维数组与复杂初始化

- 目标能力：
  - 多维数组声明、初始化、访问
- 验收标准：
  - 多维下标访问正确



### P2-2 位运算与移位

- 目标能力：
  - 位运算与移位：`& | ^ ~ << >>`
  - 复合位运算赋值：`&= |= ^= <<= >>=`
- 验收标准：
  - 每个运算符至少有独立用例覆盖
  - 运算优先级与结合性符合 C 常识



### P2-3 `union` 最小可用实现

- 目标能力：
  - 支持 `union` 定义、变量声明、成员读写
  - 明确与结构体不同的共享存储语义
- 验收标准：
  - union 成员读写行为有一致策略
  - 与 typedef、指针、成员访问组合使用不破坏现有结构体能力

---



## 6. 明确降级（暂不进入 C 兼容主线）

以下内容不是 C 语言本体，按当前策略不作为近期主线目标：

- 类、继承、`new`、`super`
- 关键字参数调用
- 范围语法（`Range`）
- 面向脚本语言的语法糖

---



## 7. 实施顺序建议（仅针对 C 兼容）



### 阶段 A（先打通主干）

- 完成 P0-1 到 P0-3：Token 化预处理器与编译管线重构、Token 宏展开语义闭环、预处理条件编译



### 阶段 B（补齐基础语言语义）

- 完成 P0-4 到 P0-6：条件判断语义、基础运算符子集、函数声明原型



### 阶段 C（补齐 C 核心模型）

- 完成 P0-7 到 P0-9：一维数组、`switch/case/default`、`typedef/enum/struct`



### 阶段 D（提升迁移能力）

- 推进 P1：指针语义、类型转换规则、`sizeof`、`const/static`、最小标准库兼容、**统一错误诊断与输出（P1-7 步骤 1–3）**



### 阶段 D+（开发者体验，可与阶段 D 并行）

- 推进 P1-7 步骤 4：警告输出统一
- 推进 P1-7 步骤 5–7（可选）：结构化 Diagnostic、词法错误统一、dump 增强



### 阶段 E（增强）

- 推进 P2：多维数组、位运算与移位、`union`

---



## 8. 统一验收原则

- 每个目标至少包含：
  - 语法层验证（可解析）
  - 语义层验证（类型/作用域/约束正确）
  - 运行时验证（执行结果正确）
- 每项至少有 2 类测试：
  - 正向样例（应通过）
  - 反向样例（应报错）
- 错误信息应包含：文件、行号、核心原因（具体格式与树形输出见 **P1-7**）

---



## 9. 完成判定（Definition of Done）

一个目标项可标记“完成”，必须同时满足：

- 语法、语义、代码生成、VM 四层已闭环
- 有对应回归测试用例
- 已更新用户文档（语法说明与示例）
- 不引入现有 C 兼容能力回退

