from verbose_c.compiler.enum import FunctionSignatureType


class FunctionSignature:
    """
    方法签名结构
    """
    def __init__(self, sign_type: FunctionSignatureType, name: str, param_count: int = 0):
        self._sign_type: FunctionSignatureType = sign_type
        self._name: str = name
        self._param_count: int = param_count
