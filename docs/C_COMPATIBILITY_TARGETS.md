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
  - 【已完成】`tests/grammar/preprocessor_test.vbc` 预处理测试通过
  - 【已完成】include 文件 token 的解析错误可输出对应文件的源码上下文
  - 【已完成】新增 Token 边界相关回归测试（`tests/grammar/preprocessor_token_boundary_test.vbc`：字符串内宏名、标识符子串、注释、函数式宏无括号等专用用例）



### P0-2 Token 宏展开语义闭环

- 目标能力：
  - 【已完成】基于 Token 序列实现普通宏、函数式宏、嵌套宏展开
  - 【已完成】用宏展开排除表（hiding 集）替代固定递归次数作为主防护机制
  - 【已完成】展开结果 rescan 时可继续匹配其他宏；当前展开链中的宏名不可再展开
  - 【已完成】`MAX_EXPANSION_DEPTH` 保留为兜底保护
  - 【已完成】字符串化（`#`）、拼接（`##`）等复杂宏能力（`macro_operators.py` + 词法 `PP_STRINGIFY`/`PP_CONCAT`）
- 当前现状：
  - 【已完成】`_expand_at` / `_rescan` / `_consume_token` 实现 token 级展开与嵌套 rescan
  - 【已完成】函数宏按形参用法分类预展开实参（`NORMAL` / `STRINGIFY` / `CONCAT`），再替换宏体并处理 `#` / `##`
  - 【已完成】`##` 粘贴后 re-lex；粘贴结果进入 `_rescan` 可继续匹配其他宏
  - 【已完成】宏体分词使用 `Lexer(macro_body=True)`（不含 `MACRO_CODE`）；行首预处理指令仍由 `MACRO_CODE` 识别
  - 【已完成】反斜杠续行 `#define` 在注册时合并宏体并 tokenize
  - 【已完成】C17 预定义宏：`__FILE__`/`__LINE__` 按宏调用点动态展开（经用户宏传递时保留调用点行号）；其余在预处理器初始化时注册
  - 【待完善】`__VA_ARGS__` / 可变参宏（见下方 P0-2 后续）
- 验收标准：
  - 【已完成】`#define A A`、`#define A B` + `#define B A` 等循环宏有专用回归测试（`tests/grammar/preprocessor_circular_macro_test.vbc`）
  - 【已完成】`#define A B` + `#define B 1` 可继续展开为最终值（`tests/grammar/preprocessor_test.vbc` 覆盖）
  - 【已完成】复杂宏样例（如 `BUILD_TOTAL(START_VALUE)`、include 导入宏）可稳定得到预期展开结果
  - 【已完成】`tests/grammar/predefined_macros_test.vbc` 覆盖预定义宏与 `__func__`
  - 【已完成】`tests/grammar/preprocessor_stringify_concat_test.vbc` 覆盖 `#` 字符串化、`##` 拼接、嵌套宏展开顺序、include 导入宏
  - 【已完成】反向样例：`tests/error/preprocessor_stringify_invalid.vbc`、`preprocessor_concat_invalid.vbc`、`preprocessor_hash_in_object_macro.vbc`

#### P0-2 后续 / P1 预处理增强（未纳入本次）

- 【待完善】`__VA_ARGS__` 与可变参宏
- 【待完善】`#` / `##` 与 `__VA_ARGS__` 组合（如 `f(...) ## g`）
- 【待完善】空实参 placemarker 与 gcc/clang 边界差异（当前 MVP 支持常见 `CAT(,x)` 粘贴）
- 【待完善】`##` 粘贴不能构成合法 token 时：当前策略为报错（非实现定义宽松容错）
- 【待完善】GNU 扩展（`__VA_OPT__` 等）
- 【交叉引用】`#if` 完整 C17 常量表达式见 P0-3



### P0-3 预处理条件编译

- 目标能力：
  - 【已完成】支持 `#if/#ifdef/#ifndef/#elif/#else/#endif`
  - 【已完成】支持 `defined(MACRO)` / `defined MACRO` 基本判断
- 当前现状：
  - 【已完成】`Preprocessor` 条件栈与指令状态机；假分支不输出 token、不注册 `#define`、不展开 `#include`
  - 【已完成】`const_expr.py` MVP 表达式求值：`0`/`1` 字面量、`defined()`、`!`/`&&`/`||`、括号、对象宏展开为整数
  - 【已完成】非法条件块抛出 `VBCCompileError`（含文件路径与行号）
  - 【待完善】`#if` 完整 C17 常量表达式（算术/位运算/比较运算符）未实现
  - 【已完成】无宏体的 `#define NAME`（include guard 常用）已支持
- 验收标准：
  - 【已完成】带条件编译分支的示例代码可稳定编译且分支选择正确（`tests/grammar/preprocessor_conditional_test.vbc`）
  - 【已完成】嵌套条件编译可正常解析（同上）
  - 【已完成】非法宏块能给出明确错误信息（`tests/error/preprocessor_*.vbc`）
  - 【已完成】include guard 场景（`tests/preprocessor_guarded.inc` + 双次 `#include`）



### P0-4 C 条件判断语义修正

- 目标能力：
  - 【已完成】`if/while/do-while/for` 条件允许标量类型（整数、浮点、指针、布尔）
  - 【已完成】逻辑非 `!` 支持整数/浮点/指针/布尔，结果为 `int`（0 或 1）
  - 【已完成】`&&` / `||` 操作数接受标量类型（与 `!` 返回 `int` 后的表达式组合兼容）
- 当前现状：
  - 【已完成】`TypeChecker` 新增 `_is_scalar_truthy_type` / `_check_condition_type`，控制流条件不再强制 `BoolType`
  - 【已完成】`visit_UnaryOpNode` 中 `Operator.NOT` 接受标量操作数，推导返回 `IntegerType(INT)`
  - 【已完成】VM `LOGICAL_NOT` 压入 `VBCInteger(0/1)`，依赖 `VBCInteger`/`VBCFloat`/`VBCPointer`/`VBCBool` 的 `__bool__` 实现 C 真值规则
  - 【已完成】`JUMP_IF_FALSE` 无需改动，已通过 `bool(condition)` 支持标量条件
- 验收标准：
  - 【已完成】`if (1)`、`if (ptr)`、`while (n)` 均可编译并行为正确（`tests/grammar/scalar_condition_test.vbc`）
  - 【已完成】`!0`、`!1`、`!ptr` 结果符合 C 预期（同上；含 `!0.0`、`!1.0` 浮点用例）
  - 【已完成】现有布尔条件与逻辑表达式回归通过（`tests/grammar/control_flow_test.vbc`、`tests/grammar/expressions_test.vbc`、`tests/pointer_test.vbc`）



### P0-5 基础运算符闭环（C 高频基础子集）

- 目标能力：
  - 【已完成】取模：`%`
  - 【已完成】复合赋值：`+= -= *= /= %=`
  - 【已完成】自增自减：`++` `--`（前置/后置）
- 当前现状：
  - 【已完成】`Grammar/verbose_c.gram` 表达式层级已纳入 `%`、复合赋值与前后缀 `++`/`--`；`Operator` 枚举与 `CompoundAssignmentNode`/`UpdateExprNode` AST 节点已对齐
  - 【已完成】`TypeChecker` 支持取模（整数操作数）、复合赋值（复用二元运算 + 赋值检查）、自增自减（可修改左值 + 整数/浮点）
  - 【已完成】`OpcodeGenerator` 生成 `MODULO` 及复合赋值/自增自减字节码；`VBCInteger.__mod__` 与 VM `MODULO` 指令闭环
- 验收标准：
  - 【已完成】每个运算符至少有独立用例覆盖（`tests/grammar/basic_operators_test.vbc`：11 种运算符形态 + `for (...; i++)`）
  - 【已完成】运算优先级与结合性符合 C 常识（`%`/`*`/`/` 位于 `multiplicative`，`+`/`-` 位于 `additive`，复合赋值右结合，前缀 `++`/`--` 高于后缀）
  - 【已完成】与赋值语句、循环更新表达式组合使用行为正确（同上；`return mod` 为 2，回归 `expressions_test`/`control_flow_test`/`pointer_test` 通过）



### P0-6 函数声明原型（Prototype）

- 目标能力：
  - 【已完成】支持顶层函数原型声明：`type name(params);`
  - 【已完成】原型形参允许仅类型（`int, int`）或类型+名字（`int a, int b`）；定义形参必须有名字
  - 【已完成】同一翻译单元内先声明后定义；允许多次完全相同的原型重复声明
  - 【已完成】`#include` 头文件原型 + 实现文件定义的跨模块基础语义（预处理 splice 为单模块）
  - 【已完成】调用时参数个数与类型检查遵循原型写入的 `FunctionType`
  - 【已完成】被调用但仅有原型、无定义时在编译期报链接错误
- 当前现状：
  - 【已完成】`ParamNode.name` 可选；新增 `FunctionDeclNode`；`Symbol.is_defined` 区分声明与定义
  - 【已完成】`Grammar/verbose_c.gram` 新增 `function_decl`、`param_item`；`TypeChecker` 实现 `_register_function_declaration` / `_register_function_definition`、`visit_FunctionDeclNode`；`OpcodeGenerator.visit_FunctionDeclNode` 为空实现
  - 【已完成】模块遍历结束后统一检查「已声明未定义」的被调函数（支持 `main` 先于定义调用、定义在后的 C 惯用顺序）
  - 【待完善】`extern` / `static` 链接语义、`int f()` 旧式非原型声明、K&R 风格定义、可变参数 `...`、类方法原型
  - 【已完成】未被调用且仅有原型的函数允许存在（不强制链接期报错）
- 验收标准：
  - 【已完成】`int add(int, int);` + 后续带函数体定义可编译运行（`tests/grammar/function_prototype_test.vbc`）
  - 【已完成】调用参数个数/类型错误由 `visit_CallNode` 按原型拒绝（同上）
  - 【已完成】`#include` 原型与实现分离可工作（`tests/grammar/function_prototype_include_test.vbc`、`tests/function_prototype_decl.inc`、`tests/function_prototype_impl.inc`）
  - 【已完成】至少 4 个反向样例有明确中文错误（`tests/error/function_prototype_conflict.vbc`、`function_prototype_mismatch.vbc`、`function_prototype_undefined.vbc`、`function_prototype_redefine.vbc`）
  - 【已完成】现有 `functions_test`、`preprocessor_test`、`classes_and_members_test` 等回归不退化



### P0-7 数组与下标访问（C17 一维数组基本子集）

- 目标能力（对齐 C17 6.5.2.1 / 6.7.6 / 6.7.9 一维数组核心语义）：
  - 【已完成】常量长度数组声明：`type name[N]`（块作用域与文件作用域）
  - 【已完成】含初始化器的长度推导：`type name[] = { ... }`
  - 【已完成】聚合初始化 `{ e1, e2, ... }`；未显式列出的元素零初始化
  - 【已完成】下标访问 `a[i]`（`i` 为整型表达式）与元素赋值
  - 【已完成】数组类型与指针类型区分；表达式语境下数组衰变为指向首元素的指针（最小子集，完整指针算术见 P1-1）
  - 【待完善】变长数组 VLA、`restrict`、柔性数组成员 — 非本期，随 P0-9 struct 或后续扩展推进
- 当前现状：
  - 【已完成】grammar、`ArrayType`、`SubscriptNode`/`InitListNode`、类型检查、字节码（`ALLOC_ARRAY`/`LOAD_INDEX`/`STORE_INDEX`/`ARRAY_DECAY`）与 VM 连续堆布局已闭环
  - 【已完成】验收用例见 `tests/grammar/array_subscript_test.vbc`
  - 【待完善】越界为运行时 `RuntimeError` 中文报错（见下方「发现问题」）
- 验收标准：
  - 【已完成】`int arr[3]; arr[0] = 1; arr[1] = arr[0] + 1;` 可编译运行且结果正确
  - 【已完成】`int arr[] = {1, 2, 3};` 长度推导为 3，读写下标正确
  - 【已完成】`int arr[5] = {1, 2};` 其余元素为 0
  - 【已完成】数组实参传入 `void f(int *p)` 可编译（衰变语义）
  - 【待完善】越界时有明确中文运行时错误（编译期：非整型下标、长度非法等已正常报错）
  - 【已完成】现有 `pointer_test` 等回归不退化
- 发现问题：
  - 数组下标越界时 VM 会抛出 `RuntimeError("数组下标越界: ...")`，但 `engine.run_source_file` 传入 VM 的 `source_code` 取自空的 `processed_code`（token 化管线后未再生成源码文本）。生成 `VBCRuntimeError` 时按行号取源码上下文触发 `IndexError`，终端显示「意外的内部错误」而非中文运行时诊断。审计用例：`tests/compatibility_audit/p0_7_array_oob_runtime_test.vbc`。



### P0-8 C 控制流补齐：`switch/case/default`

- 目标能力：
  - 支持 `switch`、`case`、`default`、`break` 语义
  - 支持 case 穿透（fallthrough）
- 当前现状：
  - 【已完成】grammar、`SwitchNode`/`SwitchLabelNode`、类型检查、字节码（链式比较分发 + fallthrough + switch 内 break）已闭环
  - 【已完成】验收用例见 `tests/grammar/switch_test.vbc`；编译期错误见 `tests/error/switch_*.vbc`
  - 【已完成】`enum` 常量可作为 case 标签（随 P0-9 补齐，见 `tests/grammar/enum_test.vbc`）
  - 【待完善】更复杂的编译期常量表达式、`char`/`unsigned`/`long` 扩展、jump table 优化 — 非本期
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
  - 【已完成】`typedef` 类型别名：语法 `typedef_decl`、`TypedefNode`、类型检查阶段解析源类型并复用 `SymbolTable.add_type_alias` 注册，字节码层完全消失；支持普通类型与指针类型别名（`typedef int* IntPtr;`）
  - 【已完成】`enum` 枚举常量：采用扁平 C 语义，成员是编译期整型常量（默认从 0 递增，支持 `= 表达式` 显式赋值），直接注入外层作用域值命名空间（而非 `Color.RED` 式命名空间对象），代码生成阶段折叠为 `LOAD_CONSTANT`，不占用变量槽
  - 【已完成】`struct` 结构体：语法 `struct_definition`、`StructType`、连续内存块布局（复用 `MemoryManager`，真实值语义），新增 `ALLOC_STRUCT`/`LOAD_FIELD`/`STORE_FIELD`/`POINTER_ADDRESS`/`COPY_STRUCT` 字节码与 `VBCStructLayout` 运行时布局描述对象；支持变量声明、`.`/`->` 成员读写、同类型拷贝初始化与拷贝赋值（`p2 = p1;` 后互不影响）
  - 【已完成】验收用例见 `tests/grammar/typedef_test.vbc`、`tests/grammar/enum_test.vbc`、`tests/grammar/struct_test.vbc`；编译期错误见 `tests/error/struct_*.vbc`
  - 【待完善】结构体嵌套字段（字段本身是 struct）、数组类型字段、结构体数组 — 非本期
  - 【待完善】结构体聚合初始化 `struct Point p = {1, 2};` — 非本期
  - 【待完善】函数按值传参/返回值的结构体拷贝语义，目前退化为地址别名，与数组当前的"退化传址"行为一致 — 非本期
  - 【待完善】匿名 struct + typedef 组合 `typedef struct { ... } Point;` — 非本期
- 验收标准：
  - typedef 可用于变量声明/函数参数/指针类型 ✅
  - enum 常量可参与表达式，并可作为 `switch/case` 标签 ✅
  - 结构体字段读写正确，`.`/`->` 语义符合 C 标准，赋值为值拷贝而非引用别名 ✅

---



## 4. P1 目标（高优先级）



### P1-1 指针语义增强

- 目标能力：
  - 指针算术：`ptr + n`、`ptr - n`、`ptr1 - ptr2`（步长按指向类型大小）
  - `&` 作用于更完整左值场景（数组元素、下标表达式等）
  - 数组—指针等价：`a[i]` 与 `*(a + i)`、数组名衰变与 `&a[0]` 等（依赖 P0-7）
- 当前现状：
  - 【部分完成】基础取址 `&var`、解引用 `*p`、指针比较与标量条件
  - 【未完成】指针算术、数组元素取址、指针差值类型为 `ptrdiff_t` 等价语义
- 验收标准：
  - 数组与指针联动场景可运行（如 `for (p = arr; p < arr + n; p++)`）
  - 指针运算结果与元素步长语义一致
  - 非法指针算术（如 `int*` 与 `float*` 相减）编译报错



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



### P1-5 底层运行时原语（标准库底座）

- 背景与动机：
  - `verbose_c/vm/builtins_functions` 的职责应定位为 **VM 可直接调用的底层运行时原语层**，类似系统调用或 POSIX/CRT fd 接口，而不是 C 标准库本身。
  - 当前已有底层原语基线：`open/read/write/close/lseek/_exit`。这些函数应尽量对齐平台底层 I/O 语义，作为后续 `<stdio.h>`、`<stdlib.h>`、`<string.h>` 等标准库实现的底座。
  - C 标准库函数应建立在 `builtins_functions` 提供的底层原语之上，但标准库本身应作为独立于 VM 的 VBC 脚本/头文件层实现，而不是 Python 内置函数或 VM 内部功能。
- 目标能力：
  - 【已完成】明确 `builtins_functions` 为底层原语注册中心：只暴露 VM 需要的最小平台能力，如 fd I/O、进程退出、后续可能的内存/时间等原语；不得把 `printf/strlen/malloc` 等标准库用户接口直接混入该层。
  - 【已完成】新增统一平台适配类 `SystemRuntime`（`verbose_c/vm/builtins_functions/system_runtime.py`），负责加载、缓存和管理底层 libc/CRT/POSIX 入口；底层 I/O 原语不再直接调用 Python `os` / `sys` 完成同等工作。
  - 【已完成】平台适配类根据平台自动识别可用动态库：Windows 优先 CRT（`ucrtbase` / `msvcrt`）并处理 `_open/_read/_write/_close/_lseek/_exit` 函数名差异；Linux 优先 `libc.so.6`；macOS 优先 `libc.dylib`。
  - 【已完成】平台适配类统一管理底层函数签名、参数/返回值转换、错误码读取（`errno` / Windows CRT errno）和资源生命周期；对外暴露稳定的 Python 调用包装，VM 只依赖该适配层。
  - 【已完成】将 `verbose_c/vm/builtins_functions` 中现有函数迁移到底层平台适配层：`open/read/write/close/lseek/_exit` 首批迁移；后续新增的底层原语也必须经由该适配层或 VM 内存模型实现。
  - 【已完成】为后续 VBC 标准库层提供稳定、最小、可测试的底层原语契约；本节不规划 `printf/strlen/fopen/malloc` 等标准库函数的实现。
- 设计要点（实施参考）：
  - 底层平台适配类建议放在独立模块（如 `verbose_c/vm/builtins_functions/libc.py`），由 `builtins_functions` 调用；不要把平台判断散落在每个内置函数文件中。
  - 标准库实现应放在独立的 VBC 脚本/头文件层，依赖 `builtins_functions` 暴露的底层原语；`builtins_functions` 不承担 C 标准库缓冲、格式化、`FILE*`、字符串 API 等高层语义。
  - `printf/puts/fread/fwrite/fclose/strlen/strcmp/malloc/free` 等接口不应在 VM 层用 Python 实现；后续若要支持，应通过 VBC 标准库代码进一步封装底层原语和 VM 内存模型。
  - 使用 `ctypes.CDLL(..., use_errno=True)` / Windows 对应 CRT 加载能力作为 MVP；若后续需要更强 ABI 控制，可再评估 `cffi` 或专用原生扩展，但不应在 MVP 引入新依赖。
  - 平台适配类初始化时完成平台探测和函数注册，缺失函数应以结构化错误暴露，避免运行到内置函数内部才出现裸 `AttributeError`。
  - 参数转换必须明确边界：`VBCInteger` ↔ `c_int` / `c_long` / `size_t`，`VBCString` ↔ `char*` / `bytes`，指针类对象 ↔ VM 内存地址或临时缓冲区；涉及 VM 堆内存的函数（如 `malloc/free/memcpy`）需要先明确与现有 `MemoryManager` 的所有权关系。
  - 底层 I/O 原语迁移时保持当前用户可见错误为中文 `VBCIOError`，底层错误码来自 libc/CRT；错误格式后续接入 P1-7。
  - 【已完成】Windows 与 POSIX 差异需显式记录：Windows 映射 `_open/_read/_write/_close/_lseek/_exit`，POSIX 映射 `open/read/write/close/lseek/_exit`；文件标志常量来自 `SystemRuntime` 维护的 CRT/POSIX 常量表，而不是直接复用 Python `os.O_*`。
  - 【MVP 边界】`O_*` / `SEEK_*` 在 C 中通常是头文件宏，不是 libc 导出的函数或变量；当前实现不尝试从动态库读取宏值，而是在 `SystemRuntime` 中按平台维护常量表。
  - 【MVP 边界】`read/write` 仍以 UTF-8 字符串桥接 VM：`read` 返回 `VBCString`，`write` 保留现有 `AnyType` 字符串化行为；真正二进制缓冲区、指针 I/O 与 VM 堆内存所有权留到后续内存模型扩展。
- 分阶段实施：

#### 步骤 1（必须）：建立底层平台适配层

- 【已完成】实现平台探测、动态库加载、函数签名注册和调用包装。
- 【已完成】提供平台适配单例 `SystemRuntime.instance()`，避免每次内置函数调用重复加载动态库。
- 【已完成】为 `errno`、缺失符号、参数转换失败提供中文运行时错误；Windows CRT 非法 fd 会在调用前拦截，避免 invalid parameter 直接终止宿主 Python 进程。

#### 步骤 2（必须）：迁移现有底层 I/O 与退出原语

- 【已完成】`native_open/read/write/close/lseek` 改为调用底层平台适配层，不再直接使用 `os.open/read/write/close/lseek`。
- 【已完成】`native__exit` 改为与 libc `_exit` / CRT `_exit` 语义对齐，同时保留 VM 内部 `NativeExitSignal` 的退出码通路，避免直接终止 Python 进程导致 dump/错误处理绕过。
- 【已完成】`STDIN/STDOUT/STDERR` 与 `O_*` / `SEEK_*` 常量改由 `SystemRuntime` 的 libc/CRT 兼容常量表定义。

- 验收标准：
  - 【已完成】`builtins_functions` 文档和实现边界清晰：它提供类似系统调用/POSIX/CRT fd 的底层原语，不直接承载 C 标准库高层接口。
  - 【已完成】`open/read/write/close/lseek/_exit` 的实现路径不再调用 Python `os` / `sys` 完成同等底层能力，而是统一经过平台适配层。
  - 【已完成】Windows、Linux、macOS 至少有平台探测分支；当前平台缺少目标符号时给出明确中文错误。
  - 【已完成】底层原语接口契约清晰，可被后续独立 VBC 标准库层调用；标准库函数不作为本节 VM 内置函数验收项。
  - 【已完成】新增回归测试覆盖：`SystemRuntime` 加载成功、I/O 成功路径（`tests/compatibility_audit/p1_5_file_io_roundtrip_test.vbc`）、I/O 错误路径（`tests/compatibility_audit/p1_5_file_io_error_test.vbc`）、`_exit` 退出码（`tests/compatibility_audit/p1_8_exit_test.vbc`）。



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



### P1-8 程序入口 `main` 与进程退出码

- 背景与动机：
  - 当前解释器采用类似 Python 的执行模型：无标准程序入口，入口文件从顶层语句起按源码顺序执行
  - 函数定义仅完成注册，不会自动执行；即便定义了 `int main()`，若未在顶层显式写 `main();` 则不会进入 `main` 函数体
  - 现有测试用例普遍在文件末尾手动调用 `main();`（如 `tests/grammar/functions_test.vbc`），与标准 C 程序习惯不符
  - 标准 C 以 `int main(void)` / `int main(int argc, char *argv[])` 为进程入口；部分环境亦存在非标准的 `void main()`，迁移时应尽量兼容
- 目标能力：
  - 【已完成】在入口模块中识别符合条件的 `main` 函数定义：`int main()`（MVP 先支持无参形式），并兼容非标准的 `void main()`
  - 【已完成】若存在上述 `main` 定义，在顶层代码按现有顺序执行完毕后**自动调用** `main()`，无需源码末尾手写 `main();`
  - 【已完成】**保留**现有顶层顺序执行语义不变：函数/类型定义注册、全局变量声明与初始化、顶层可执行语句、顶层独立代码块等仍按源码顺序在调用 `main` 之前执行
  - 【已完成】`int main()` 中 `return expr;` 的整型返回值作为进程退出码传递给命令行（CLI 以 `sys.exit(code)` 退出）
  - 【已完成】`void main()` 正常执行结束时退出码为 `0`；若运行期异常或 `VBCRuntimeError`，退出码为非零（与现有错误处理一致）
  - 【已完成】若入口模块不存在 `main` 定义，行为与现在完全一致（纯顺序执行，退出码 `0`）
  - 【已完成】提供 C 风格内置函数 `_exit(int status)`，可在运行时立即终止程序并使用 `status` 作为进程退出码
- 当前现状：
  - 【已完成】`OpcodeGenerator.visit_ModuleNode` 在顶层语句生成后检测无参 `int main()` / `void main()`，若顶层没有显式 `main();`，则注入自动入口调用
  - 【已完成】自动入口调用使用 `LOAD_GLOBAL_VAR "main"` + `CALL_FUNCTION 0` + `SET_EXIT_CODE`；专用 `SET_EXIT_CODE` 避免把普通顶层表达式残留值误当退出码
  - 【已完成】`VBCVirtualMachine.excute` 返回整型退出码，`run_source_file` 通过 `RunResult.exit_code` 暴露，`cli.main` 调用 `sys.exit(result.exit_code)`
  - 【已完成】`int main` 中的 `return;` 作为兼容特例映射为退出码 `0`，其他非 `void` 函数仍保持必须返回表达式的类型检查规则
  - 【已完成】`_exit` 实现在 `verbose_c/vm/builtins_functions/exit.py`，通过 `NativeExitSignal` 通知 VM 正常停止执行并设置退出码
  - 【已完成】新增 P1-8 回归用例：`tests/compatibility_audit/p1_8_auto_main_return_code_test.vbc`、`p1_8_top_level_before_main_test.vbc`、`p1_8_void_main_auto_entry_test.vbc`、`p1_8_explicit_main_no_double_call_test.vbc`、`p1_8_no_main_script_compat_test.vbc`、`p1_8_bad_main_signature_no_auto_test.vbc`、`p1_8_int_main_empty_return_test.vbc`、`p1_8_exit_test.vbc`
- 与 C 标准差异（可接受/分阶段）：


| 行为 | C17 / 常见实现 | 目标实现 |
| ---- | -------------- | -------- |
| 程序入口 | 从 `main` 开始，全局对象初始化先于 `main` | 顶层语句先于 `main` 执行（保留脚本化顺序语义）；`main` 在顶层代码之后自动调用 |
| `main` 形参 | `argc`/`argv`/`envp` 等 | MVP 仅无参 `int main()` / `void main()`；带参形式后续扩展 |
| `void main()` | 非标准，部分编译器扩展 | 兼容调用，退出码视为 `0` |
| 显式 `main();` | 标准 C 中顶层调用 `main()` 合法但少见 | 需避免与自动调用重复执行（见验收标准） |


- 设计要点（实施参考）：
  - 【已完成】**检测时机**：代码生成阶段基于全局符号表与入口模块 AST 检测签名匹配的 `main`（名称 `main`，返回 `int` 或 `void`，MVP 形参为空）
  - 【已完成】**代码生成**：在 `visit_ModuleNode` 末尾，若存在 `main` 且策略允许，生成 `LOAD_GLOBAL_VAR "main"` + `CALL_FUNCTION 0` + `SET_EXIT_CODE`
  - 【已完成】**退出码通路**：`VBCVirtualMachine.excute` 返回整型退出码 → `run_source_file` 写入 `RunResult.exit_code` → `cli.main` 调用 `sys.exit(code)`
  - 【已完成】**重复调用**：若源码顶层已显式调用 `main()`，自动入口跳过，避免重复执行
  - 【已完成】**立即退出**：内置 `_exit(int)` 抛出 VM 内部信号，由 VM 捕获后设置退出码并停止执行，不直接调用 Python `sys.exit`
- 验收标准：
  - 【已完成】仅含 `int main() { return 42; }`、无顶层 `main();` 的 `.vbc` 可编译运行，且 shell 退出码为 `42`
  - 【已完成】含顶层初始化语句 + `int main()` 时，初始化语句先于 `main` 体执行（`p1_8_top_level_before_main_test.vbc` 退出码为 `3`）
  - 【已完成】`void main() { ... }` 可自动进入并正常结束，退出码为 `0`
  - 【已完成】无 `main` 定义的脚本式顶层代码行为与改动前一致
  - 【已完成】源码末尾已写 `main();` 时 `main` 只执行一次
  - 【已完成】`return;`（无表达式）在 `int main` 中退出码为 `0`（与 C 一致）
  - 【已完成】签名不匹配的带参 `main` 不会误触发自动入口
  - 【已完成】`_exit(7);` 可立即终止程序，shell 退出码为 `7`



### P1-9 断言 `assert`（`<assert.h>`）

- 背景与动机：
  - 标准 C 通过 `<assert.h>` 提供 `assert(expr)` 宏，用于在调试构建中检测不变量；大量迁移自 C 的代码依赖该机制
  - 当前 `verbose-c` 语法、类型检查、字节码与 VM 均无 `assert` 关键字或 `<assert.h>` 等价能力；代码库中仅有的 `assert` 为 Python 工具链内部断言，与用户源码无关
- 目标能力（对齐 C17 7.2 / B.2 `assert.h`）：
  - 提供 `#include <assert.h>`（或内置等价头）后，可使用 `assert(scalar-expr);`
  - 未定义 `NDEBUG` 时：`expr` 为假（按 C 标量真值规则）则输出诊断信息并异常终止（等价 `abort()`）
  - 定义 `NDEBUG` 时（含 `#define NDEBUG` 或编译选项 `-DNDEBUG`）：`assert(expr)` 展开为 `((void)0)`，不产生运行时检查
  - `assert` 为宏而非语言关键字；表达式在 `NDEBUG` 定义时不应被求值（与 C 一致）
  - 失败时诊断信息至少包含：源文件、行号、失败表达式文本（格式可与 **P1-7** 统一）
- 依赖关系：
  - **P0-3** 条件编译（`NDEBUG` 分支）
  - **P0-4** 标量真值规则（`assert` 条件判断）
  - **P1-5** 底层运行时原语（`_exit` 或等价进程退出通路；`abort` 由后续 VBC 标准库层封装）
  - **P1-6** `#include <assert.h>` 搜索路径（若采用系统头风格）
  - **P1-7** 统一错误诊断（断言失败输出格式）
- 当前现状：
  - 【未完成】grammar 无 `assert` 语句；无 `AssertNode` 等 AST
  - 【未完成】无 `assert.h` 头文件或预处理器内置宏
  - 【未完成】VM 无专用断言失败指令；无 `abort()` 运行时原语
  - 【未完成】测试目录无 `assert` 相关 `.vbc` 用例
- 设计要点（实施参考）：
  - **推荐路径**：以标准库宏实现为主，而非新增语言关键字——在 `assert.h` 中根据 `NDEBUG` 展开为检查调用或空操作，与 gcc/clang 迁移路径一致
  - **检查实现**：可落地为内建函数 `__assert_fail(expr, file, line)` 或 VM 指令 `ASSERT` + 条件跳转；宏层保持 C 外观
  - **表达式副作用**：`NDEBUG` 分支必须用宏展开消去 `expr`，不得生成对其的求值字节码
- 与 C 标准差异（可接受/分阶段）：


| 行为 | C17 | 目标实现 |
| ---- | --- | -------- |
| 失败动作 | 调用 `abort()`，实现定义是否输出到 `stderr` | 输出中文/结构化诊断后非零退出或 `VBCRuntimeError` |
| `NDEBUG` | 仅宏展开层消除 | 同左；需与 P0-3 `#if defined(NDEBUG)` 一致 |
| 头文件路径 | `<assert.h>` 系统 include | MVP 可先内置虚拟头，后续对齐 P1-6 `-I` |


- 验收标准：
  - 未定义 `NDEBUG` 时，`assert(1);` 通过，`assert(0);` 运行时失败并输出文件、行号与表达式
  - 定义 `NDEBUG` 后，含副作用的 `assert(func());` 中 `func` 不被调用（专用副作用检测用例）
  - `assert(ptr);`、`assert(0.0);` 等标量条件行为符合 C 真值规则
  - 至少 2 类测试：正向（断言通过）、反向（断言失败）；另含 `NDEBUG` 禁用用例
  - 与 **P1-8** 退出码策略一致：断言失败时进程退出码为非零

---



## 5. P2 目标（增强项）



### P2-1 多维数组与复杂初始化（C17 6.7.6 扩展）

- 目标能力（依赖 P0-7 一维数组闭环）：
  - 【未完成】多维声明 `type name[R][C]` 及嵌套聚合初始化
  - 【未完成】多维下标 `a[i][j]` 与行主序存储布局
  - 【未完成】部分初始化、多维 `{0}` 清零、字符串字面量初始化 `char s[] = "hi"`
- 当前现状：
  - 【未完成】未开始；grammar / 类型 / 后端均无多维数组路径
- 验收标准：
  - `int m[2][3] = {{1,2,3},{4,5,6}}; m[1][2]` 结果正确
  - `char s[] = "abc";` 长度与内容与 C17 一致
  - 初始化器形状不匹配时有明确错误



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

- 【已完成】P0-4：条件判断语义修正
- 【已完成】P0-5：基础运算符子集
- 【已完成】P0-6：函数声明原型



### 阶段 C（补齐 C 核心模型）

- 【待完善】P0-7：一维数组（运行时越界错误展示未完成，见 P0-7 发现问题）
- 【已完成】P0-8：`switch/case/default`
- 【已完成】P0-9：`typedef` / `enum` / `struct`



### 阶段 D（提升迁移能力）

- 推进 P1：指针语义、类型转换规则、`sizeof`、`const/static`、**底层平台适配层与运行时原语迁移（P1-5 步骤 1–2）**、**统一错误诊断与输出（P1-7 步骤 1–3）**、**程序入口 `main` 与进程退出码（P1-8）**、**断言 `assert` / `<assert.h>`（P1-9，依赖 P1-5 与 P1-7）**



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

