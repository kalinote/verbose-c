import ctypes
from ctypes import c_void_p, c_char, c_int8, c_int16, c_int32, c_int64
from ctypes import c_uint8, c_uint16, c_uint32, c_uint64, c_float, c_double
from typing import Optional, Dict, List, Tuple
import threading

from verbose_c.object.object import VBCObject
from verbose_c.object.enum import VBCObjectType


class MemoryBlock:
    """内存块描述符"""
    def __init__(self, address: int, size: int, is_free: bool = False):
        self.address = address
        self.size = size
        self.is_free = is_free
        self.allocated_object: Optional[VBCObject] = None


class NativeMemoryManager:
    """
    基于ctypes的原生内存管理器
    
    实现真实的内存地址操作，同时保持与现有MemoryManager接口兼容
    """
    
    def __init__(self, heap_size: int = 1024 * 1024, enable_debugging: bool = False):
        """
        初始化原生内存管理器
        
        Args:
            heap_size: 堆大小，默认1MB
            enable_debugging: 是否启用调试模式
        """
        self.heap_size = heap_size
        self.enable_debugging = enable_debugging
        
        # 创建原生内存缓冲区
        self._heap_buffer = ctypes.create_string_buffer(heap_size)
        self._heap_base_address = ctypes.cast(self._heap_buffer, c_void_p).value
        
        # 内存分配管理
        self._current_offset = 0
        self._free_blocks: List[MemoryBlock] = []
        self._allocated_blocks: Dict[int, MemoryBlock] = {}
        
        # 对象映射表（保持与Python对象系统的兼容性）
        self._address_to_object: Dict[int, VBCObject] = {}
        self._object_to_address: Dict[VBCObject, int] = {}
        
        # 线程安全
        self._lock = threading.Lock()
        
        # 调试信息
        self._debug_log: List[str] = []
        
        if self.enable_debugging:
            self._log(f"初始化原生内存管理器: 堆大小={heap_size} bytes, 基地址=0x{self._heap_base_address:08x}")
    
    def _log(self, message: str):
        """记录调试信息"""
        if self.enable_debugging:
            self._debug_log.append(message)
            print(f"[NativeMemoryManager] {message}")
    
    def _is_valid_address(self, address: int) -> bool:
        """检查地址是否在堆范围内"""
        return self._heap_base_address <= address < self._heap_base_address + self.heap_size
    
    def _find_free_block(self, size: int, alignment: int = 8) -> Optional[MemoryBlock]:
        """查找满足条件的空闲块"""
        for block in self._free_blocks:
            if block.is_free and block.size >= size:
                return block
        return None
    
    def _align_address(self, address: int, alignment: int = 8) -> int:
        """地址对齐"""
        return (address + alignment - 1) & ~(alignment - 1)
    
    def allocate(self, value: VBCObject, alignment: int = 8) -> int:
        """
        为VBCObject分配内存，返回真实内存地址
        
        保持与现有MemoryManager接口兼容
        """
        with self._lock:
            # 计算所需内存大小（暂时统一使用指针大小，后续会根据类型优化）
            size = ctypes.sizeof(c_void_p)
            
            # 尝试从空闲块分配
            free_block = self._find_free_block(size, alignment)
            if free_block:
                address = free_block.address
                self._free_blocks.remove(free_block)
                
                # 如果空闲块过大，分割之
                if free_block.size > size:
                    remaining_block = MemoryBlock(
                        address + size, 
                        free_block.size - size, 
                        is_free=True
                    )
                    self._free_blocks.append(remaining_block)
            else:
                # 从堆顶分配新内存
                aligned_offset = self._align_address(self._current_offset, alignment)
                
                if aligned_offset + size > self.heap_size:
                    raise MemoryError(f"堆内存不足: 需要 {size} bytes, 剩余 {self.heap_size - aligned_offset} bytes")
                
                address = self._heap_base_address + aligned_offset
                self._current_offset = aligned_offset + size
            
            # 记录分配的内存块
            block = MemoryBlock(address, size, is_free=False)
            block.allocated_object = value
            self._allocated_blocks[address] = block
            
            # 建立对象<->地址映射
            self._address_to_object[address] = value
            self._object_to_address[value] = address
            
            # 将对象序列化到内存（现在先简单存储对象引用）
            obj_ptr = ctypes.cast(id(value), c_void_p)
            ctypes.memmove(address, ctypes.addressof(obj_ptr), ctypes.sizeof(c_void_p))
            
            self._log(f"分配内存: 地址=0x{address:08x}, 大小={size}, 对象={value}")
            return address
    
    def read(self, address: int) -> VBCObject:
        """
        从指定地址读取VBCObject
        
        保持与现有MemoryManager接口兼容
        """
        with self._lock:
            if not self._is_valid_address(address):
                raise MemoryError(f"内存访问冲突: 试图读取无效地址 0x{address:08x}")
            
            if address not in self._address_to_object:
                raise MemoryError(f"地址 0x{address:08x} 未分配或已释放")
            
            obj = self._address_to_object[address]
            self._log(f"读取内存: 地址=0x{address:08x}, 对象={obj}")
            return obj
    
    def write(self, address: int, value: VBCObject):
        """
        向指定地址写入VBCObject
        
        保持与现有MemoryManager接口兼容
        """
        with self._lock:
            if not self._is_valid_address(address):
                raise MemoryError(f"内存访问冲突: 试图写入无效地址 0x{address:08x}")
            
            if address not in self._allocated_blocks:
                raise MemoryError(f"地址 0x{address:08x} 未分配")
            
            # 更新对象映射
            old_obj = self._address_to_object.get(address)
            if old_obj and old_obj in self._object_to_address:
                del self._object_to_address[old_obj]
            
            self._address_to_object[address] = value
            self._object_to_address[value] = address
            
            # 更新内存块信息
            block = self._allocated_blocks[address]
            block.allocated_object = value
            
            # 更新内存中的对象引用
            obj_ptr = ctypes.cast(id(value), c_void_p)
            ctypes.memmove(address, ctypes.addressof(obj_ptr), ctypes.sizeof(c_void_p))
            
            self._log(f"写入内存: 地址=0x{address:08x}, 对象={value}")
    
    def deallocate(self, address: int):
        """
        释放指定地址的内存
        """
        with self._lock:
            if address not in self._allocated_blocks:
                raise MemoryError(f"试图释放未分配的地址 0x{address:08x}")
            
            block = self._allocated_blocks[address]
            del self._allocated_blocks[address]
            
            # 清理对象映射
            obj = self._address_to_object.get(address)
            if obj:
                del self._address_to_object[address]
                if obj in self._object_to_address:
                    del self._object_to_address[obj]
            
            # 将块标记为空闲
            block.is_free = True
            block.allocated_object = None
            self._free_blocks.append(block)
            
            # 合并相邻的空闲块
            self._merge_free_blocks()
            
            self._log(f"释放内存: 地址=0x{address:08x}, 大小={block.size}")
    
    def _merge_free_blocks(self):
        """合并相邻的空闲内存块"""
        self._free_blocks.sort(key=lambda b: b.address)
        
        merged = []
        for block in self._free_blocks:
            if merged and merged[-1].address + merged[-1].size == block.address:
                # 合并相邻块
                merged[-1].size += block.size
            else:
                merged.append(block)
        
        self._free_blocks = merged
    
    def get_heap_info(self) -> Dict:
        """获取堆状态信息（用于调试）"""
        with self._lock:
            total_allocated = sum(block.size for block in self._allocated_blocks.values())
            total_free = sum(block.size for block in self._free_blocks)
            
            return {
                "heap_size": self.heap_size,
                "base_address": f"0x{self._heap_base_address:08x}",
                "current_offset": self._current_offset,
                "allocated_bytes": total_allocated,
                "free_bytes": total_free,
                "allocated_blocks": len(self._allocated_blocks),
                "free_blocks": len(self._free_blocks),
                "utilization": f"{(total_allocated / self.heap_size) * 100:.1f}%"
            }
    
    def get_debug_log(self) -> List[str]:
        """获取调试日志"""
        return self._debug_log.copy()
    
    def clear_debug_log(self):
        """清空调试日志"""
        self._debug_log.clear()


# 内存管理器适配器，支持新旧两套系统的切换
class MemoryManagerAdapter:
    """
    内存管理器适配器，支持渐进式迁移
    """
    
    def __init__(self, use_native: bool = False, **kwargs):
        self.use_native = use_native
        
        if use_native:
            self.manager = NativeMemoryManager(**kwargs)
        else:
            from verbose_c.vm.memory import MemoryManager
            self.manager = MemoryManager()
    
    def allocate(self, value: VBCObject) -> int:
        """统一的分配接口"""
        return self.manager.allocate(value)
    
    def read(self, address: int) -> VBCObject:
        """统一的读取接口"""
        return self.manager.read(address)
    
    def write(self, address: int, value: VBCObject):
        """统一的写入接口"""
        self.manager.write(address, value)
    
    def get_info(self) -> Dict:
        """获取内存管理器信息"""
        if hasattr(self.manager, 'get_heap_info'):
            return self.manager.get_heap_info()
        else:
            return {
                "type": "legacy",
                "heap_size": len(self.manager._heap) if hasattr(self.manager, '_heap') else 0
            } 