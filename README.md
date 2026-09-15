# Verbose-C

一个用Python实现的类C语言编译器和虚拟机，支持从源代码编译到字节码并执行。项目采用完整的编译器架构，包含词法分析、语法分析、语义分析、代码生成和虚拟机执行等完整流程。

## 项目简介

Verbose-C 是一个教学性质的编程语言实现，旨在展示现代编译器的完整工作流程。该项目实现了：

- **自制解析器生成器 (PPG)**: 基于PEG语法的解析器自动生成工具
- **完整编译流程**: 预处理 → 词法分析 → 语法分析 → 语义分析 → 代码生成
- **字节码虚拟机**: 基于栈的虚拟机，支持垃圾回收和内存管理
- **类C语法**: 支持函数、变量、控制流、指针、类等核心语言特性

## 工作原理

### 1. 编译阶段
```
源代码(.vbc) → 预处理 → 词法分析 → 语法分析 → AST → 语义分析 → 字节码生成
```

- **预处理器**: 处理宏定义和条件编译
- **词法分析器**: 将源代码转换为Token序列
- **语法分析器**: 通过自制的PEG解析器生成器从语法文件自动生成
- **语义分析**: 类型检查、符号表管理、作用域分析
- **代码生成**: 生成针对自定义虚拟机的字节码指令

### 2. 执行阶段
```
字节码 → 虚拟机加载 → 指令执行 → 内存管理 → 垃圾回收
```

- **虚拟机**: 基于栈的字节码解释器
- **内存管理**: 支持指针操作和动态内存分配
- **垃圾回收**: 自动内存回收机制
- **内置函数**: 提供I/O、类型检查等基础功能

### 3. 支持的语言特性

- **数据类型**: char、short、int、long、long long、float、double、bool、string、指针、类
- **统一数值语义**: 类型检查、O1、VM 和 Windows x64 native 共用整数提升、混算、窄化及溢出规则；详见 [C-P1-2 类型转换与算术语义](docs/C_COMPATIBILITY_TARGETS.md#类型与共同算术类型)。旧 version 1 字节码需从源码重新编译。
- **控制流**: if/else、while、do-while、for循环
- **函数**: 函数定义、调用、参数传递、返回值
- **面向对象**: 类定义、继承、实例化
- **指针操作**: 取地址(&)、解引用(*)
- **内置函数**: 文件I/O函数等

## 安装依赖环境

使用 Python 3.13 及以上版本

```bash
pip install -r requirement.txt
```

## 使用方法

### 运行源代码文件
```bash
python -m verbose_c.cli example.vbc
```

### 编译并输出详细信息
```bash
python -m verbose_c.cli example.vbc --log all
```

### 重新生成解析器
```bash
python -m verbose_c.cli --compile-parser
```

### 调试虚拟机执行
```bash
python -m verbose_c.cli example.vbc --debug-vm --log all
```

### 导出 IR 与控制流图
```bash
python -m verbose_c.cli example.vbc --dump ir --compile-only
```

`--dump` 支持 `parser`、`tokens`、`preprocess`、`ast`、`opcode`、`ir`、`machine`、`optimize`、`const`、`label`、`vm`、`memory`、`all`。

### 统一导出 Native 产物
```bash
python -m verbose_c.cli example.vbc --compile-only --emit native-bin,native-map,native-pe --emit-dir build/native
```

`--emit` 支持 `native-listing`、`native-bin`、`native-text-bin`、`native-pe`、`native-map` 和一次导出全部类型的 `native-bundle`。统一导出会按输入文件名组织产物，并生成包含路径、大小和 SHA-256 的 `.native.manifest.json`。`--emit-dir` 可省略，此时输出到入口文件所在目录的 `<入口文件名>_emit_out_<时间戳>` 目录；未设置 `--emit` 时，单独提供 `--emit-dir` 不生效。

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

当前 native I/O 子集限于标准流和字符串写入；`open/close/lseek`、字符串拼接及完整 GC 仍未实现。长时间循环读取时，已返回字符串会保留到程序结束，尚无逐对象回收。VM 的普通文件接口继续可用。只有使用字符串或 I/O 的程序才附加运行时；已有纯标量 PE 路径保留。

产物 map 的 `schema_version=2` 记录 `.text`、只读 `.rdata`、可写 `.idata`、系统导入及相对地址。`native-bin` / `native-text-bin` 内存执行从 map 恢复数据和导入；独立 exe 不需要 map。当前采用固定首选基址与 RIP 相对寻址，尚未提供基址重定位表。

验收测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_native_io.py
```

## 编译器自身打包为可执行文件
```bash
nuitka verbose_c/cli.py --follow-imports --standalone
```

## O1 字节码优化
```bash
python -m verbose_c.cli example.vbc -O1
```
