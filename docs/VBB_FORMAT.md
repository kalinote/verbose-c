# Verbose-C 字节码文件格式（`.vbb`）

本文档描述 Verbose-C 当前实现的 `.vbb`（Verbose-C Bytecode）紧凑二进制格式。实现位于 [`verbose_c/fs/artifact_store.py`](../verbose_c/fs/artifact_store.py)。

- **格式版本**：`1`
- **字节序**：小端（little-endian）
- **目标 ABI 字符串**：`verbose-c-vm`
- **默认产物路径**：入口源文件同目录下的 `__vbccache__/<stem>.vbb`

当前版本 **不兼容** 早期 JSON 载荷格式；加载旧文件会抛出 `VBCBytecodeError`。

---

## 1. 文件总体布局

```text
+------------------+
| File Header      |  固定 64 字节
+------------------+
| Section Directory|  section_count × 24 字节
+------------------+
| Section Payloads |  按目录顺序紧密拼接
+------------------+
```

加载顺序：

1. 校验文件头（魔数、版本、文件大小、header 长度）
2. 解析 section 目录，校验每个 section 的 offset/length/checksum
3. 校验所有 section payload 拼接后的 SHA-256
4. 按 section 解码并重建运行时对象图
5. 返回模块级 `bytecode` 与 `metadata`

---

## 2. 基础编码

### 2.1 定长整数

| 类型 | 大小 | 说明 |
|------|------|------|
| `u8` | 1 | 无符号 8 位 |
| `u16` | 2 | 无符号 16 位 |
| `u32` | 4 | 无符号 32 位 |
| `u64` | 8 | 无符号 64 位 |
| `f64` | 8 | IEEE 754 双精度浮点 |

### 2.2 `varuint`

无符号可变长整数，每字节低 7 位为数据，最高位 `1` 表示后续还有字节。

### 2.3 `varint`

有符号可变长整数，使用 zigzag 编码后再写入 `varuint`：

```text
encoded = value * 2            (value >= 0)
encoded = -value * 2 - 1       (value < 0)
```

### 2.4 `bytes`

```text
varuint byte_len
byte_len × u8
```

### 2.5 可空字符串索引

字符串统一存放在 `STRINGS` section。引用规则：

- `0` 表示 `null`
- `N (>0)` 表示 `strings[N - 1]`

---

## 3. 文件头（64 字节）

结构体格式：`<4sHHIHHQQ32s`

| 偏移 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0 | `magic` | `4s` | 固定为 `b"VBB\0"` |
| 4 | `version` | `u16` | 当前为 `1` |
| 6 | `flags` | `u16` | 保留，当前写 `0` |
| 8 | `header_size` | `u32` | 文件头长度，当前为 `64` |
| 12 | `section_count` | `u16` | section 数量，当前为 `9` |
| 14 | `reserved` | `u16` | 保留，当前写 `0` |
| 16 | `directory_offset` | `u64` | section 目录起始偏移，当前为 `64` |
| 24 | `file_size` | `u64` | 整个文件字节数 |
| 32 | `payload_sha256` | `32s` | 所有 section payload 拼接后的 SHA-256 |

---

## 4. Section 目录项（24 字节）

结构体格式：`<HHQQI`

| 字段 | 类型 | 说明 |
|------|------|------|
| `section_id` | `u16` | section 标识 |
| `flags` | `u16` | 保留，当前写 `0` |
| `offset` | `u64` | payload 在文件中的起始偏移 |
| `length` | `u64` | payload 字节长度 |
| `checksum32` | `u32` | payload 的 CRC32（`zlib.crc32`） |

约束：

- `section_id` 不可重复
- 各 section 范围不可重叠
- 必须包含下文列出的全部 9 个 section

### 4.1 Section ID

| ID | 名称 | 用途 |
|----|------|------|
| 1 | `STRINGS` | 全局字符串驻留表 |
| 2 | `MODULE` | 模块入口元数据 |
| 3 | `CONSTANTS` | 常量项表与常量池块 |
| 4 | `BYTECODE` | 字节码块集合 |
| 5 | `FUNCTIONS` | 函数对象定义表 |
| 6 | `CLASSES` | 类对象定义表 |
| 7 | `STRUCTS` | 结构体布局表 |
| 8 | `LINE_TABLES` | 行号映射表集合 |
| 9 | `DEBUG` | 调试信息（labels、函数编译结果） |

---

## 5. Section 载荷格式

### 5.1 `STRINGS` (1)

```text
varuint string_count
repeat string_count times:
    bytes utf8_string
```

### 5.2 `MODULE` (2)

```text
varuint source_path_id        // 可空字符串索引
varuint target_abi_id         // 字符串索引，指向 "verbose-c-vm"
varuint module_bytecode_id    // BYTECODE 块索引
varuint module_constant_pool_id
varuint module_line_table_id
```

### 5.3 `CONSTANTS` (3)

分为两部分：常量项表、常量池块表。

**常量项表：**

```text
varuint constant_count
repeat constant_count times:
    u8 constant_tag
    payload...
```

**常量池块表：**

```text
varuint pool_count
repeat pool_count times:
    varuint entry_count
    repeat entry_count times:
        varuint constant_id
```

#### 常量标签（`constant_tag`）

| 值 | 名称 | payload |
|----|------|---------|
| 1 | `INTEGER` | `varuint object_type_id` + `varint value` |
| 2 | `FLOAT` | `varuint object_type_id` + `f64 value` |
| 3 | `BOOL` | `u8`（`0`/`1`） |
| 4 | `STRING` | `varuint string_id` |
| 5 | `NULL` | 无 |
| 16 | `FUNCTION` | `varuint function_id` |
| 17 | `CLASS` | `varuint class_id` |
| 18 | `STRUCT` | `varuint struct_id` |

常量池块通过 `constant_id` 引用常量项；模块、函数各自持有自己的 pool 块索引。

### 5.4 `BYTECODE` (4)

```text
varuint block_count
repeat block_count times:
    varuint instruction_count
    repeat instruction_count times:
        u16 opcode_value
        u8 operand_tag
        operand_payload...
```

#### 操作数标签（`operand_tag`）

| 值 | 名称 | payload |
|----|------|---------|
| 0 | `NONE` | 无操作数 |
| 1 | `INT` | `varint` |
| 2 | `FLOAT` | `f64` |
| 3 | `BOOL` | `u8` |
| 4 | `STRING` | `varuint string_id` |
| 5 | `TUPLE` | `varuint count` + 递归 `value` × count |
| 6 | `LIST` | `varuint count` + 递归 `value` × count |
| 7 | `DICT` | `varuint count` + 递归 `(key, value)` × count |
| 8 | `OBJECT_TYPE` | `varuint object_type_id` |
| 9 | `NULL` | 无 |

`opcode_value` 对应 [`verbose_c/compiler/opcode.py`](../verbose_c/compiler/opcode.py) 中 `Opcode` 枚举值。加载后恢复为 `(Opcode,)` 或 `(Opcode, operand)` 元组。

### 5.5 `FUNCTIONS` (5)

```text
varuint function_count
repeat function_count times:
    varuint name_id
    varuint bytecode_block_id
    varuint constant_pool_id
    varuint param_count
    varuint local_count
    varuint source_path_id        // 可空字符串索引
    varuint lineno_table_id
```

### 5.6 `CLASSES` (6)

```text
varuint class_count
repeat class_count times:
    varuint name_id
    varuint super_count
    repeat super_count times:
        varuint class_id
    varuint method_count
    repeat method_count times:
        varuint method_name_id
        varuint function_id
    varuint field_count
    repeat field_count times:
        varuint field_name_id
        varuint constant_id
```

父类、方法、字段均通过 ID 引用，不在类定义中嵌套完整对象。

### 5.7 `STRUCTS` (7)

```text
varuint struct_count
repeat struct_count times:
    varuint name_id
    varuint field_count
    repeat field_count times:
        varuint field_name_id
        varuint object_type_id      // 0 表示无类型
```

### 5.8 `LINE_TABLES` (8)

```text
varuint table_count
repeat table_count times:
    varuint entry_count
    repeat entry_count times:
        varuint bytecode_offset
        varint source_line
```

### 5.9 `DEBUG` (9)

```text
value labels                              // 递归 VALUE 编码
varuint function_result_count
repeat function_result_count times:
    varuint name_id
    varuint bytecode_block_id
    varuint constant_pool_id
    value labels
```

用于恢复 `metadata["labels"]` 与 `metadata["function_compilation_results"]`，供 `PipelineRecorder` dump 使用；不影响 VM 执行语义。

---

## 6. `VBCObjectType` 稳定 ID

| ID | 类型 |
|----|------|
| 1 | `CUSTOM` |
| 2 | `VOID` |
| 3 | `CLASS` |
| 4 | `CHAR` |
| 5 | `SHORT` |
| 6 | `INT` |
| 7 | `LONG` |
| 8 | `LONGLONG` |
| 9 | `NLINT` |
| 10 | `FLOAT` |
| 11 | `DOUBLE` |
| 12 | `NLFLOAT` |
| 13 | `BOOL` |
| 14 | `NULL` |
| 15 | `POINTER` |
| 16 | `LIST` |
| 17 | `MAP` |
| 18 | `MODULE` |
| 19 | `STRING` |
| 20 | `FUNCTION` |
| 21 | `NATIVE_FUNCTION` |
| 22 | `INSTANCE` |
| 23 | `RANGE` |
| 24 | `STRUCT` |

未知 ID 在加载时抛出 `VBCBytecodeError`。

---

## 7. 对象图与去重规则

写入前，编译器先把运行时对象收集为表结构：

- 字符串：全局驻留
- 字节码：按块存储（模块、各函数、调试结果各自引用块 ID）
- 常量：全局 `constant_entries` + 多个 `constant_pool_blocks`
- 函数 / 类 / 结构体：独立对象表，通过 ID 互相引用

去重策略：

- 同一 `VBCFunction` / `VBCClass` / `VBCStruct` 实例按 Python 对象身份（`id()`）去重
- 函数内部常量、类字段默认值、调试常量池中的对象，也进入同一套常量表

**不支持** 写入的运行时对象：

- `VBCPointer`
- `VBCInstance`
- `VBCNativeFunction`

`VBCString` 保存的是已解析字符串值；加载时绕过 `VBCString.__init__`，避免二次转义。

---

## 8. 加载后恢复结构

`ArtifactStore.load_bytecode()` 返回：

```python
bytecode: list[tuple[Opcode, ...]]
metadata: {
    "constant_pool": list,
    "lineno_table": list[tuple[int, int]],
    "source_path": str | None,
    "target_abi": str,
    "labels": dict,
    "function_compilation_results": dict,
}
```

该结构与 [`verbose_c/engine/engine.py`](../verbose_c/engine/engine.py) 中 `run_bytecode_file()` / `VBCVirtualMachine.excute()` 的输入一致。

---

## 9. 校验与错误处理

加载时会依次检查：

| 检查项 | 失败时 |
|--------|--------|
| 文件可读 | `VBCBytecodeError` |
| 文件头长度 | 截断错误 |
| 魔数 | 魔数不匹配 |
| 版本 | 版本不匹配 |
| `file_size` | 文件大小不一致 |
| section 目录范围 | 目录非法 |
| 重复 section ID | 重复 section |
| section offset/length | 范围非法或重叠 |
| section CRC32 | checksum 失败 |
| 缺失必要 section | 缺少 section |
| payload SHA-256 | 载荷校验失败 |
| 表项索引越界 | 索引越界 |
| 未知 tag / opcode / type ID | 格式错误 |

所有错误均通过 `VBCBytecodeError` 抛出，并附带文件路径。

---

## 10. CLI 与产物路径

| 场景 | 行为 |
|------|------|
| 编译 `.vbc` | 始终生成 `.vbb` |
| 未指定 `-o/--output` | 写入 `<source_dir>/__vbccache__/<stem>.vbb` |
| 指定 `-o` | 写入用户指定路径 |
| 输入 `.vbb` | 跳过编译，直接加载执行 |
| `--compile-only` | 只生成 `.vbb`，不执行 |

---

## 11. 版本策略

- 当前仅定义 **version 1** 紧凑二进制格式
- 读写双方使用同一 `FORMAT_VERSION`
- 未来若升级格式，应递增 `version` 并在 loader 中显式拒绝不支持的版本
- 旧版 JSON `.vbb` 不在支持范围内
