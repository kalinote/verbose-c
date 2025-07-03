from verbose_c.object.object import VBCObject

class MemoryManager:
    """
    一个简单的内存管理器，用于模拟内存的分配和读写。
    初期使用 Python list 来模拟内存，索引即为地址。
    """
    def __init__(self):
        # 使用列表模拟堆内存
        self._heap: list[VBCObject] = []

    def allocate(self, value: VBCObject) -> int:
        """
        在内存中为一个对象分配空间，并返回其地址。

        Args:
            value (VBCObject): 需要存储的对象。

        Returns:
            int: 分配的内存地址。
        """
        # TODO: 后续可以实现更复杂的内存分配策略，比如查找可复用的空间
        address = len(self._heap)
        self._heap.append(value)
        return address

    def read(self, address: int) -> VBCObject:
        """
        根据地址从内存中读取对象。

        Args:
            address (int): 内存地址。

        Returns:
            VBCObject: 存储在该地址的对象。
        """
        if not (0 <= address < len(self._heap)):
            raise MemoryError(f"内存访问冲突: 试图读取无效地址 {address}")
        return self._heap[address]

    def write(self, address: int, value: VBCObject):
        """
        将一个新值写入指定的内存地址。

        Args:
            address (int): 目标内存地址。
            value (VBCObject): 需要写入的新对象。
        """
        if not (0 <= address < len(self._heap)):
            raise MemoryError(f"内存访问冲突: 试图写入无效地址 {address}")
        self._heap[address] = value

