# 内存管理与指针改造方案

## 1. 背景与目标

Verbose-C 目前通过 `vm/memory.py` 的 `MemoryManager` 使用 `list` 模拟堆内存，指针仅保存列表索引。这一实现易于原型验证，但无法满足：

1. 访问**真实地址空间**，以更贴近 C 语义。
2. 为后续性能优化（Cython/C 扩展）奠定基础。
3. 支持指针算术、结构体、数组等高级特性。

因此需要对 **内存管理子系统** 与 **基础数据对象** 进行重构。

### 1.1 需求清单（功能 & 非功能）

**功能需求：**
1. 支持 `&` 取址、`*` 解引用，保证与 C 语义一致。
2. 支持以下数据类型在原始内存中的直接读写：
   * 有符号整数：`char`/`short`/`int`/`long`/`long long`。
   * 浮点数：`float`/`double`。
   * 布尔、字符（视为 1 字节整型）。
3. 指针可参与比较 (`==`/`!=`/`<`/`<=`/`>`/`>=`)；算术 (`+`/`-`) 仅允许 `pointer ± integer`（先留空，后续迭代）。
4. 保留无限位宽 `NLINT` / `NLFLOAT` 类型现行行为，不参与本轮内存落地。
5. 运行时出现以下非法行为需抛出 `MemoryError`：
   * 越界访问。
   * 解引用空指针。
   * Use-After-Free（指针指向已释放块）。

**非功能需求：**
1. 设计应保持 **纯 Python** 可运行，避免强制 C 扩展依赖。
2. 读/写 1e6 次性能退化不超过当前 list 实现的 2×。
3. 通过现有测试用例 + 新增内存相关用例后，CI 必须全部 green。
4. 关键接口（MemoryManager / VBCPrimitive / 指针指令）须具备单元测试覆盖率 ≥ 90%。

### 1.2 设计原则
* **渐进式演进**：重构保持向后兼容，旧对象仍可在 VM 中正常运行。
* **单一职责**：MemoryManager 只负责字节存储与安全检查，不涉 GC 策略。
* **类型驱动**：所有低层操作由 `TYPE_TABLE` 提供元信息，避免魔数。
* **可测试**：每步改动都引入对应测试，保障行为一致。

---

## 2. 现状分析

### 2.1 编译 – 执行流程概览

```mermaid
graph TD;
    A[源码 .vbc] --> B[Preprocessor];
    B --> C[Tokenizer];
    C --> D[GeneratedParser];
    D --> E[AST];
    E --> F[TypeChecker];
    F --> G[OpcodeGenerator];
    G --> H[Bytecode + ConstantPool];
    H --> I[VBCVirtualMachine];
    I --> J[MemoryManager(list)];
```

### 2.2 MemoryManager 现实现

* `_heap: list[VBCObject]`   —— 地址 = 列表索引。
* `allocate(obj) -> int`     —— `append` 返回索引。
* `read(addr) -> VBCObject`  —— 直接下标访问。
* `write(addr, obj)`         —— 覆盖列表元素。

### 2.3 指针实现现状

* `VBCPointer(address:int, target_type)` 保存"索引地址"。
* `LOAD_ADDRESS / LOAD_BY_POINTER / STORE_BY_POINTER` 指令依赖 `MemoryManager`。
* 未实现指针算术、边界检查、对齐。

---

## 3. 总体设计

### 3.1 MemoryManager_CTYPES

| 功能 | 描述 |
| ---- | ---- |
| 真实地址 | 利用 `ctypes` 申请字节缓冲区，`ctypes.addressof()` 获取物理地址（Python 进程空间内）。 |
| 接口 | `malloc / free / read / write` 四大接口。|
| 安全 | 内部维护 `addr → buffer` 映射，做越界与 UAF 检测。|

### 3.2 VBCPrimitive 抽象

* 继承 `VBCObjectWithGC`。
* 仅保存：
  * `addr : int` —— 指向堆中原始字节。
  * `ctype` —— 对应 `ctypes` 类型（如 `c_int32`）。
* 暴露 API：`load() -> Python 原生值`、`store(val)`。

### 3.3 TYPE_TABLE

统一维护各基础类型的元信息。

```python
TYPE_TABLE = {
    VBCObjectType.INT32:  {"ctype": ctypes.c_int32,  "size": 4,  "align": 4},
    VBCObjectType.FLOAT64:{"ctype": ctypes.c_double, "size": 8,  "align": 8},
    # ... 其余类型
}
```

### 3.4 GC 协同

* `MemoryManager` 保存强引用，确保 buffer 生命周期覆盖 VBCPrimitive。  
* `VBCPrimitive.__del__` 调用 `MemoryManager.free(addr)` 以移除映射。

### 3.5 数据布局与对齐

| 类型 | 字节数 | 对齐 | 备注 |
| ---- | ---- | ---- | ---- |
| char / bool | 1 | 1 | × |
| short | 2 | 2 | little-endian |
| int | 4 | 4 | 跟随宿主 CPU |
| long | 8 | 8 | 64 位平台统一 8 字节 |
| long long | 8 | 8 | × |
| float | 4 | 4 | IEEE-754 |
| double | 8 | 8 | IEEE-754 |

> Unlimited 类型暂不在内存分配，仍存 Python 对象。

### 3.6 指针运算策略（预研）
1. `ptr + n` → `addr + n * sizeof(T)`；`ptr - ptr` 返回相差元素个数。
2. 编译期检测 `n` 为整数；运行时越界由 MemoryManager 捕获。
3. 暂不支持自增 `++p`，该语法在 parser 层缺失，后续 grammar 扩展。

---

## 4. 详细模块设计

### 4.1 MemoryManager 接口

```python
class BaseMemoryManager(ABC):
    @abstractmethod
    def malloc(self, size:int) -> int: ...
    @abstractmethod
    def free(self, addr:int): ...
    @abstractmethod
    def read(self, addr:int, ctype): ...
    @abstractmethod
    def write(self, addr:int, ctype, value): ...
```

`MemoryManager_CTYPES` 实现：

```python
class MemoryManager_CTYPES(BaseMemoryManager):
    def __init__(self):
        self._heap: dict[int, ctypes.Array] = {}
    def malloc(self, size:int) -> int:
        buf = (ctypes.c_uint8 * size)()
        addr = ctypes.addressof(buf)
        self._heap[addr] = buf
        return addr
```

### 4.2 基本数据类型对象示例

```python
class VBCInt32(VBCPrimitive):
    def __init__(self, init_val: int = 0):
        super().__init__(VBCObjectType.INT32, ctypes.c_int32)
        self.store(init_val)
```

### 4.3 指令集调整

| Opcode | 变更点 |
| ------ | ------ |
| STORE_LOCAL_VAR / STORE_GLOBAL_VAR | 如果值为 `VBCPrimitive` 直接保存其 `addr`；否则新 malloc 并写入。 |
| LOAD_LOCAL_VAR / LOAD_GLOBAL_VAR | 根据地址 + `target_type` 构造 `VBCPrimitive` 压栈。 |
| LOAD_BY_POINTER / STORE_BY_POINTER | 通过 `TYPE_TABLE` 获取 `ctype` 读写。 |

### 4.4 算术与比较

* 在执行期对 `VBCPrimitive` 先 `.load()` 转 Python 原生值计算，再`.store()` 写回。  
* NLINT / NLFLOAT 保持现状，直接在对象层运算。

### 4.5 实现步骤要点
1. **创建 `memory/manager.py`**：含 `BaseMemoryManager`、`MemoryManager_CTYPES`、未来 `MemoryManager_MMAP` stub。
2. **替换 VM 引用**：`self.memory = MemoryManager_CTYPES()` 可通过 CLI flag 切换。
3. **实现 `VBCPrimitive`**：
   ```python
   class VBCPrimitive(VBCObjectWithGC):
       def __init__(self, obj_type, ctype):
           super().__init__(obj_type)
           self.addr = Memory.malloc(ctypes.sizeof(ctype))
           self.ctype = ctype
       def load(self):
           return Memory.read(self.addr, self.ctype)
       def store(self, value):
           Memory.write(self.addr, self.ctype, value)
   ```
4. **修改 Opcode 处理器**：
   * `STORE_*` 使用 `getattr(val, "addr", None)` 判断是否已有地址。
   * `LOAD_*` 构造对应 `VBCPrimitive`：
   ```python
   cinfo = TYPE_TABLE[target_type]
   primitive = VBCPrimitive(target_type, cinfo["ctype"])
   primitive.addr = addr  # 直接绑定
   stack.push(primitive)
   ```
5. **测试用例示例**：
   ```c
   int a = 10;
   int* p = &a;
   *p = 20;
   print(a); // -> 20
   ```
6. **边界测试**：malloc 8 字节后尝试读写第 9 字节应抛错。

---

## 5. 里程碑与时间计划

| 阶段 | 任务 | 预计工期 |
| ---- | ---- | ---- |
| M0 | 类型枚举与 TYPE_TABLE 建立 | 0.5d |
| M1 | MemoryManager_CTYPES 实现 + 单测 | 1.5d |
| M2 | VBCPrimitive 抽象 & 基础类型实现 | 2d |
| M3 | VM 指令改造 | 1.5d |
| M4 | 算术/比较适配 | 1d |
| M5 | GC 协同与安全检测 | 1d |
| M6 | 测试覆盖 & CI | 1.5d |
| M7 | 文档 & Demo | 0.5d |
| **合计** | **8-9 人日** |

---

## 6. 风险与缓解

1. **Segmentation Fault（ctypes）**  
   * 统一在 MemoryManager 做越界检查。  
   * 开启环境变量 `PYTHONFAULTHANDLER=1`。  
2. **GC 与 buffer 生命周期错配**  
   * `addr → buffer` 强引用字典。  
3. **性能不达标**  
   * 热路径可后续以 Cython 重写，或切到 C 扩展。  
4. **指针算术 & 对齐复杂**  
   * 优先实现 `&`、`*` 操作；算术留到后续版本。  

---

## 7. 后续扩展

* 指针运算（ptr ± n）、多级指针。
* 结构体与数组：编译器计算布局，MemoryManager 负责 raw block。
* NLINT/ NLFLOAT 原生内存实现（多精度）。
* 多线程内存模型与锁策略。

---

> **备注**：如对方案有任何意见，可在 Issue / PR 中讨论。 