from verbose_c.error import VBCCompileError


class NativeLoweringError(VBCCompileError):
    """Native 后端 lowering 失败。"""
    category = "后端错误"


class NativeCodegenError(VBCCompileError):
    """Native 机器码生成失败。"""
    category = "后端错误"
