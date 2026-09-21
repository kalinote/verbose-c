# Verbose-C

一个用 Python 实现的教学型类 C 语言编译器，支持源码编译、字节码缓存与 VM 执行，以及 Windows x64 稳定子集的独立可执行文件生成。它不是完整的 C17 实现；VM 和原生后端的支持范围不同。

## 项目简介

Verbose-C 是一个教学性质的编程语言实现，旨在展示现代编译器的完整工作流程。该项目实现了：

- **自制解析器生成器 (PPG)**: 基于PEG语法的解析器自动生成工具
- **源码编译**: 词法分析 → Token 预处理 → 语法分析 → 类型检查 → 可选 O1 → 字节码
- **字节码与缓存**: `.vbb` 二进制读写、include 依赖摘要和入口翻译单元缓存复用
- **字节码虚拟机**: 基于栈的解释器、模拟地址空间和受管理对象 GC
- **原生后端**: 字节码 → IR / CFG → Machine IR → x64 机器码 → Windows PE 可执行文件
- **类 C 语法**: 函数、变量、控制流、一维数组、指针、结构体与类；具体限制见下文和目标清单

当前提供 `-O0`、`-O1`；O2/O3、热点统计和 JIT 尚未实现。

## 工作原理

### 1. 编译阶段

```
源代码(.vbc) → 原始 Token → 宏/include/条件预处理 → AST → 类型检查
  → 可选 typed AST O1 → 字节码与标签解析 → 可选字节码 O1 → .vbb
```

- **预处理器**: 在 Token 上处理宏、相对路径 include 和条件编译；完整 C 预处理语义尚未实现，已知限制见 [C-P0-3](docs/C_COMPATIBILITY_TARGETS.md) 和 [待修复问题](docs/FIXME.md)
- **词法分析器**: 将源代码转换为Token序列
- **语法分析器**: 通过自制的PEG解析器生成器从语法文件自动生成
- **语义分析**: 类型检查、符号表管理、作用域分析
- **代码生成**: 生成针对自定义虚拟机的字节码指令

新编译会继续尝试构建 IR、Machine IR 和机器码。普通 VM 路径允许记录已知的后端能力限制后继续执行；显式请求原生执行或导出时，必须成功生成对应产物。内部编译器异常始终报告失败。缓存命中或直接加载 `.vbb` 时，不恢复 AST；后端产物按请求从字节码重新构建。

### 2. 执行阶段

```
字节码 → 初始化 VM → 执行模块顶层语句 → 按入口规则调用 main → HALT / exit
                        ↳ 指令执行期间访问内存；受管理对象分配达到阈值时触发 GC
```

- **虚拟机**: 基于栈的字节码解释器
- **内存管理**: `MemoryManager` 提供变量、数组和结构体的模拟地址槽；尚无通用 `malloc/free` 接口或地址槽回收复用
- **垃圾回收**: 对 VM 登记的对象执行标记清扫；不等于完整模拟堆回收，也不是程序结束后的固定步骤
- **内置函数**: `open/read/write/close/lseek/_exit/exit`；另提供标准流与文件标志常量

无 `main` 时按顺序执行顶层代码，正常结束返回 `0`，顶层 `return` 编译失败。有无参 `int main()` / `void main()` / `bool main()` 时，在顶层代码之后自动调用；直接位于顶层的独立 `main();` 会阻止这次自动调用。自动调用的整型返回值作为退出码，布尔返回值统一为 `true → 1`、`false → 0`，void 返回 `0`；VM、字节码重载和原生执行遵循同一规则。普通显式调用的返回值不自动成为退出码，`exit(code)` / `_exit(code)` 可提前终止执行。

### 3. 支持的语言特性

- **数据类型**: char、short、int、long、long long、float、double、bool、string、一维数组、指针、typedef、enum、struct、类；VM 另有 `unlimited int/float` 扩展
- **统一数值语义**: 类型检查、O1、VM 和 Windows x64 native 共用整数提升、混算、窄化及溢出规则；详见 [C-P1-2 类型转换与算术语义](docs/C_COMPATIBILITY_TARGETS.md#类型与共同算术类型)。旧 version 1 字节码需从源码重新编译。
- **控制流**: if/else、while、do-while、for、switch/case/default、break、continue
- **函数**: 原型声明、定义、调用、参数传递、返回值和递归
- **面向对象**: VM 支持类、继承、实例化和成员访问；构造链、类转型等仍有未完成项
- **指针操作**: 取地址(&)、解引用(*)
- **内置函数**: 文件I/O函数等

## 安装依赖环境

使用 Python 3.13 及以上版本。以下命令均在项目根目录的 PowerShell 中执行；原生执行与完整验收需要 Windows x64。先设置 UTF-8，再创建并使用项目虚拟环境：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirement.txt
```

已有 `.venv` 时可跳过创建步骤。解析器默认使用根目录的 `parser.py` 和 `Grammar/verbose_c.gram`；不要在其他工作目录直接照抄运行命令。

## 使用方法

### 运行源代码文件

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc
```

### 编译、缓存与字节码运行

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc --compile-only -o .\build\array_sort.vbb -O1
.\.venv\Scripts\python.exe -m verbose_c.cli .\build\array_sort.vbb
```

未指定 `-o` 时，源码产物位于 `<源目录>/__vbccache__/<文件名>.vbb`，依赖清单位于旁边的 `.vbb.deps.json`。缓存检查入口和实际 include 文件的 SHA-256、编译器修订号、字节码版本、ABI 及优化等级；命中后直接加载 `.vbb`。请求原生执行/导出或 `--dump ir`、`--dump machine`、`--dump all` 会重新编译源码。编译器和语法文件的修改不会自动参与摘要检查：语法变更后使用 `-rp`，编译器语义变更时还需维护缓存修订号。

`.vbb` 输入不接受 `--compile-only` 或 `-o`；`-O` 不会重新优化已有字节码。`--compile-only` 关闭源码的默认 VM 执行，可与原生导出组合。

### 编译并输出详细信息

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc --log all
```

### 重新生成解析器

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\Grammar\verbose_c.gram --compile-parser
```

CLI 的此模式使用上述固定语法路径生成根目录 `parser.py`。也可在源码编译时传入 `-rp/--refresh-parser`；仅修改语法文件不会自动重新生成已有解析器。

### 调试虚拟机执行

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc --log vm --dump vm,memory
```

### 导出 IR 与控制流图

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc --dump ir,machine --compile-only
```

`--dump` 支持 `parser`、`tokens`、`preprocess`、`ast`、`opcode`、`ir`、`machine`、`optimize`、`const`、`label`、`vm`、`memory`、`all`。

报告写入根目录 `dumps/`。`--dump ir` / `all` 要求 IR 生成成功；Machine IR 与机器码的已知能力限制可记录到报告中。`--log` 支持 `compile`、`vm`、`parser`、`all`。使用 `--help` 查看完整 CLI 选项。

### 错误诊断与输出通道

源码编译、字节码加载、VM 和 Native 内存执行的错误诊断统一写入 **stderr**，失败退出码为 `1`；正常退出遵循上述入口规则。默认关闭日志、dump 且没有警告时，stdout 仅包含程序输出。警告和显式开启的日志仍写入 stdout；`--no-warn` 当前控制类型检查警告，尚未统一控制预处理警告，也不会屏蔽错误。

解析错误使用树形正文，包含实际出错的 include 文件、行列、源码指示及规则栈；类型错误按原顺序展示，运行时错误保留已有调用栈。终端列号从 `1` 开始。加载 `.vbb` 失败时定位产物文件，执行失败时使用内嵌源码位置；源码不可读时省略上下文。开启 `--dump` 后，「错误信息」节保存与终端相同的诊断正文，内部异常同时保留 Python traceback。

独立 exe 沿用 Native 运行时诊断，错误原因、stderr 通道和失败退出码与 VM 一致，VM 可以附带更完整的调用栈。

### 统一导出 Native 产物

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc --compile-only --emit native-bin,native-map,native-pe --emit-dir .\build\native
```

`--emit` 支持 `native-listing`、`native-bin`、`native-text-bin`、`native-pe`、`native-map` 和一次导出全部类型的 `native-bundle`。统一导出会按输入文件名组织产物，并生成包含路径、大小和 SHA-256 的 `.native.manifest.json`。`--emit-dir` 可省略，此时输出到入口文件所在目录的 `<入口文件名>_emit_out_<时间戳>` 目录；未设置 `--emit` 时，单独提供 `--emit-dir` 不生效。

`--emit` 本身不关闭默认 VM 执行。只导出源码产物时加 `--compile-only`；需要独立程序时优先使用下面的正式 `--emit-exe` 入口。

### 编译独立 Windows 可执行文件

稳定 AOT 入口接受 `.vbc` 或 `.vbb`，只编译、不运行目标程序：

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\native_io_greeting.vbc --emit-exe .\build\greeting.exe -O1
.\build\greeting.exe
```

`--emit-exe PATH` 明确指定 exe 路径；`-o/--output` 仍指定 `.vbb` 路径。需要检查产物时，可附加 `--emit native-map --emit-dir build/maps`，或使用 `--emit native-bundle`。正式编译不与 `--run-native-*` 等调试执行选项组合。缓存输入 `.vbb` 使用其编译时已有的优化结果，`-O` 只对源码生效。

| 稳定 AOT 子集 | 支持范围 |
| --- | --- |
| 数值与控制流 | 定宽有符号整数、bool、float/double、隐式/显式数值转换、分支、循环、switch、递归、寄存器及栈参数、受限全局标量 |
| 数组 | 定长一维局部／全局标量数组；支持清零、完整/部分初始化、下标读写、复合赋值、自增减及跨函数传参 |
| 入口与退出 | 顶层初始化和无参 `int main()` / `void main()` / `bool main()`；bool 返回 0/1，正常返回及 `exit/_exit` 使用 Windows 32 位进程退出码 |
| 字符串与 I/O | 字符串传值、别名、比较及标准输入输出，详见下表 |
| 运行时错误 | 整数/浮点溢出、除零、转换失败及数组下标越界输出具体中文原因；失败均输出 STDERR 并以 1 退出 |
| 部署 | exe 自带启动与运行时，仅依赖系统 KERNEL32.dll；支持 ASLR、DEP 和实际 DIR64 基址重定位 |

数组元素支持 `char/short/int/long/long long/bool/float/double`，每个数组包含 8 字节长度头，每元素使用 8 字节内部槽。局部数组每次执行声明重新初始化，函数调用和递归各自拥有独立存储；全局数组在顶层初始化后由各函数共享。拥有数组存储的栈帧、调用窗口及保留空间合计上限为 4096 字节，过大时给出源码位置和编译诊断。

数组形参支持 `int *a`、`int a[]` 和 `int a[10]`，后两者调整为指针形参；声明中的长度不覆盖调用方的实际长度。Native 在内部使用带边界的借用引用，参数占一个机器字，指向首元素，长度位于该地址前 8 字节；支持局部别名、修改调用方数据、递归转传及寄存器／栈传参。可传入完整数组或 `&a[0]`，读写前均按实际长度检查边界。库存示例 `tests/grammar/practical_vm_inventory.vbc` 和分函数排序示例 `tests/grammar/practical_array_sort.vbc` 均可生成独立 exe。

复合赋值和前后置自增减只求值一次左值，包含 `p[i++] += 5`、`(*p)++`、函数调用产生的指针解引用及成员访问。结构体和类成员场景由 VM 执行，Native 沿用其支持范围。

Native 数组返回、保存偏移后的数组地址、数组地址保存到全局指针、对象元素数组、一般指针操作、结构体、类、普通文件 I/O、字符串拼接和逐对象 GC 属于后续扩展；当前遇到这些能力会明确编译失败。预处理、解析和类型检查与 VM 共用；只对已知后端能力限制允许 VM 降级，内部编译器异常会明确失败并保留 traceback。

### Windows 原生 I/O 示例

在 Windows x64 上编译并运行中文交互程序：

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\native_io_greeting.vbc --compile-only --emit native-pe --emit-dir .\build\native_io -O1
.\build\native_io\native_io_greeting.exe
```

生成的 `.exe` 内置机器码运行时，只导入 Windows 自带的 `KERNEL32.dll`；部署时只需要复制该 exe，不需要 Python、CRT、额外 DLL 或导出的 manifest。`-O0` 和 `-O1` 使用相同的 I/O 语义。接口依据 [Windows x64 调用约定](https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention) 和 [Windows 控制台 I/O](https://learn.microsoft.com/en-us/windows/console/high-level-console-i-o) 实现。

| 接口 / 行为 | 约定 |
| --- | --- |
| `read(STDIN, count)` | 返回最多 count 个输入字节解码得到的字符串；count 范围为 0～16 MiB，0 立即返回空串。 |
| `write(STDOUT/STDERR, string)` | 完整写入，重试短写，返回写出的 UTF-8 字节数；零进展视为失败。 |
| 控制台 | 使用 `ReadConsoleW/WriteConsoleW`，支持中文和 emoji，不改变控制台代码页；按 Enter 提交，行首 Ctrl+Z 后 Enter 表示 EOF。 |
| 重定向 | 使用 `ReadFile/WriteFile`；文件、管道按 UTF-8 读写，保留 CRLF、NUL 和反斜杠，不添加 BOM。 |
| EOF / 编码 | EOF 返回空字符串；每次读取独立按 UTF-8 解码，非法或被 count 截断的序列替换为 `�`，与 VM 一致。输入的 `\n` 等文本不会再次转义。 |
| 错误与退出 | 无效标准流、负数或过大长度、系统读写失败及分配失败均停止执行，诊断写入 STDERR，进程退出码为 1；系统错误附 Win32 错误码。正常 `return/exit` 保留退出码。STDERR 本身失效时仍以非零码退出。 |
| 字符串生命周期 | UTF-8 常量位于只读节，值是指向“8 字节长度 + 文本”的地址；支持赋值、别名、传参、返回、相等比较和空串判断。读入结果保存在本次执行的私有堆，正常结束、显式退出和运行时失败均销毁堆；转换临时缓冲区及时释放。 |

当前 native I/O 子集限于标准流和字符串写入；`open/close/lseek`、字符串拼接及完整 GC 仍未实现。长时间循环读取时，已返回字符串会保留到程序结束，尚无逐对象回收。VM 的普通文件接口继续可用。正式 `--emit-exe` 总是附加运行时，确保纯标量程序也有错误诊断；调试导出仍按需附加运行时。

调试 map 的 `schema_version=1/2` 保持兼容。正式 AOT 使用 `schema_version=3`，在 `.text`、只读 `.rdata`、可写 `.idata` 之外增加 `.aot` 启动节和只读可丢弃的 `.reloc`；启动中的 64 位目标地址由 Windows loader 修补。所有 map、节内容、导入、重定位和文件布局均校验后写出，并读回复核。布局遵循 [Microsoft PE/COFF 规范](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format#the-reloc-section-image-only)。`native-bin` / `native-text-bin` 内存执行从 map 恢复数据和导入；独立 exe 不需要 map。

运行时 ABI 版本为 1：语言标量和字符串占用 8 字节槽，浮点参数按 Windows x64 约定放入 XMM 参数寄存器。运行时函数以 RAX 返回值、RDX 传递状态（0 为正常，1 为显式退出，2～9 为数值错误，10 为数组越界，20 起为 I/O 错误）；R11 保存语言全局帧，R12 保存私有堆及标准流状态。系统调用使用 Windows x64 的四个参数寄存器、32 字节 shadow space 和 16 字节栈对齐。`read/write/equal` 分别接收 `(int64,int64)`、`(int64,string)`、`(string,string)`；返回 `string/int64/bool64`。

验收测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_native_io.py
```

### 完整回归验收

```powershell
.\scripts\verify.ps1
```

脚本复用项目 `.venv` 和已安装的依赖，检查 Windows x64、重新生成解析器，再运行全部测试。每次在 `build/verify-<唯一编号>` 下创建独立临时目录和 JUnit 报告，避免共享临时目录的权限或并发冲突。GitHub Actions 的 Windows 工作流执行相同入口，覆盖 O0/O1、VM、字节码重载、原生内存执行、独立 exe、强制异址重定位及损坏产物拒绝。可用 `-TestPaths tests/test_native_aot.py` 运行专项验收。

## 编译器自身打包为可执行文件

依赖中包含 Nuitka，可用于打包 Python 编译器。下面是打包入口，不是 `.vbc` 的 AOT 命令：

```powershell
.\.venv\Scripts\python.exe -m nuitka verbose_c/cli.py --follow-imports --standalone --output-dir=build/compiler
```

现有命令未自动收集 `Grammar/verbose_c.gram` 和生成的 `parser.py`，运行时仍受工作目录约束；编译器自身的独立分发尚不属于当前 AOT 验收范围。

## O1 优化

```powershell
.\.venv\Scripts\python.exe -m verbose_c.cli .\tests\grammar\practical_array_sort.vbc -O1 -rp --compile-only --dump optimize
```

O1 同时包含 typed AST 优化和字节码窥孔优化。示例中的 `-rp` 强制刷新解析器和源码编译，以便获得本次优化统计；缓存命中不会恢复这些统计。详见 [O1 优化技术说明](docs/O1_OPTIMIZATION.md)。

## 文档与流程图

- [项目模块关系图](docs/PROJECT_RELATIONSHIP.mmd)
- [程序主执行流程](docs/PROGRAM_EXECUTION_FLOW.mmd)、[编译流程](docs/COMPILATION_FLOW.mmd)、[VM 指令循环](docs/VM_EXECUTION_FLOW.mmd)
- [C 兼容目标与当前限制](docs/C_COMPATIBILITY_TARGETS.md)
- [扩展功能、原生后端与 JIT 目标](docs/FEATURE_IMPLEMENTATION_TARGETS.md)
- [VBB 字节码格式](docs/VBB_FORMAT.md)
- [已处理问题与后续工作](docs/FIXME.md)
