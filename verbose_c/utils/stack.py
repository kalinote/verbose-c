
class Stack:
    """
    栈数据结构实现
    """
    def __init__(self):
        self._items = []
        
    def push(self, item):
        """
        将元素压入栈顶
        """
        self._items.append(item)
        
    def pop(self):
        """
        弹出栈顶元素
        """
        if not self.is_empty():
            return self._items.pop()
        else:
            raise IndexError("pop from empty stack")

    def is_empty(self):
        """
        判断栈是否为空
        """
        return len(self._items) == 0
    
    def peek(self, index: int = 0):
        """
        查看栈中指定深度的元素（从栈顶开始，0为栈顶）
        """
        if self.size() > index:
            return self._items[-1 - index]
        else:
            raise IndexError("peek index out of range")

    def size(self):
        """
        返回栈中元素的数量
        """
        return len(self._items)

    def clear(self):
        """
        清空栈
        """
        self._items = []
