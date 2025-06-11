
def hash_(t):
    """
    计算hash值，目前先直接使用Python内置的hash计算方法
    
    单独拿出来封装一下便于以后修改
    """
    if t is None:
        return 0
    
    return hash(t)
