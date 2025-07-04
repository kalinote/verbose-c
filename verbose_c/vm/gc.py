from typing import TYPE_CHECKING
from verbose_c.object.object import VBCObjectWithGC

if TYPE_CHECKING:
    from verbose_c.vm.core import VBCVirtualMachine

class GarbageCollector:
    """
    垃圾回收管理器
    """
    def __init__(self, vm: 'VBCVirtualMachine'):
        self.vm = vm
        self.heap: list['VBCObjectWithGC'] = []
        self.threshold = 1000  # 初始分配阈值

    def allocate(self, obj: 'VBCObjectWithGC') -> None:
        """
        分配一个新对象，并检查是否需要触发GC。
        """
        self.heap.append(obj)
        if len(self.heap) > self.threshold:
            self.collect()

    def collect(self) -> None:
        """
        执行一次完整的垃圾回收周期。
        """
        # print("GC：开始执行垃圾回收...")
        
        # 1. 标记阶段
        self._mark()
        
        # 2. 清除阶段
        self._sweep()
        
        # 3. 调整下一次GC的阈值
        self.threshold = len(self.heap) * 2
        # print(f"GC：回收完成。堆大小: {len(self.heap)}, 下次回收阈值: {self.threshold}")

    def _mark(self) -> None:
        """
        标记阶段：从根对象开始，迭代标记所有可达对象。
        """
        worklist = self.vm.get_roots()
        
        while worklist:
            obj = worklist.pop()

            # 如果不是VBCObject对象，或者已经标记过，则跳过
            if not isinstance(obj, VBCObjectWithGC) or obj._gc_marked:
                continue

            obj._gc_marked = True

            # 将对象的子对象添加到工作列表中以供后续处理
            if hasattr(obj, '_gc_walk'):
                for child in obj._gc_walk():
                    worklist.append(child)

    def _sweep(self) -> None:
        """
        清除阶段：遍历堆，回收所有未被标记的对象。
        """
        new_heap = []
        for obj in self.heap:
            if obj._gc_marked:
                # 存活对象：取消标记，为下一次GC做准备
                obj._gc_marked = False
                new_heap.append(obj)
            else:
                # 垃圾对象：不加入新的heap，将被Python的GC回收
                # print(f"GC：回收对象 {obj}") # 可以取消注释这行来观察回收了哪些对象
                pass
        
        self.heap = new_heap
