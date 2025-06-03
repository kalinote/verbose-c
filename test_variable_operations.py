#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试变量操作类指令的实现
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from verbose_c.vm.core import VBCVirtualMachine
from verbose_c.compiler.opcode import Opcode

def test_local_variables():
    """测试局部变量操作"""
    print("=== 测试局部变量操作 ===")
    
    vm = VBCVirtualMachine()
    
    # 模拟字节码：存储和加载局部变量
    bytecode = [
        (Opcode.LOAD_CONSTANT, 0),    # 加载常量 42
        (Opcode.STORE_LOCAL_VAR, 0),  # 存储到局部变量 0
        (Opcode.LOAD_LOCAL_VAR, 0),   # 加载局部变量 0
        (Opcode.DEBUG_PRINT,),        # 调试输出
        (Opcode.HALT,)                # 停机
    ]
    
    constants = [42]
    
    try:
        vm.excute(bytecode, constants)
        print("✅ 局部变量操作测试成功")
    except Exception as e:
        print(f"❌ 局部变量操作测试失败: {e}")

def test_global_variables():
    """测试全局变量操作"""
    print("\n=== 测试全局变量操作 ===")
    
    vm = VBCVirtualMachine()
    
    # 模拟字节码：存储和加载全局变量
    bytecode = [
        (Opcode.LOAD_CONSTANT, 0),      # 加载常量 "Hello"
        (Opcode.STORE_GLOBAL_VAR, "x"), # 存储到全局变量 x
        (Opcode.LOAD_GLOBAL_VAR, "x"),  # 加载全局变量 x
        (Opcode.DEBUG_PRINT,),          # 调试输出
        (Opcode.HALT,)                  # 停机
    ]
    
    constants = ["Hello"]
    
    try:
        vm.excute(bytecode, constants)
        print("✅ 全局变量操作测试成功")
    except Exception as e:
        print(f"❌ 全局变量操作测试失败: {e}")

def test_scope_management():
    """测试作用域管理"""
    print("\n=== 测试作用域管理 ===")
    
    vm = VBCVirtualMachine()
    
    # 模拟字节码：作用域嵌套
    bytecode = [
        (Opcode.LOAD_CONSTANT, 0),    # 加载常量 10
        (Opcode.STORE_LOCAL_VAR, 0),  # 存储到局部变量 0
        (Opcode.ENTER_SCOPE,),        # 进入新作用域
        (Opcode.LOAD_CONSTANT, 1),    # 加载常量 20
        (Opcode.STORE_LOCAL_VAR, 1),  # 存储到局部变量 1
        (Opcode.LOAD_LOCAL_VAR, 1),   # 加载局部变量 1
        (Opcode.DEBUG_PRINT,),        # 调试输出 (应该是 20)
        (Opcode.EXIT_SCOPE,),         # 退出作用域
        (Opcode.LOAD_LOCAL_VAR, 0),   # 加载局部变量 0
        (Opcode.DEBUG_PRINT,),        # 调试输出 (应该是 10)
        (Opcode.HALT,)                # 停机
    ]
    
    constants = [10, 20]
    
    try:
        vm.excute(bytecode, constants)
        print("✅ 作用域管理测试成功")
    except Exception as e:
        print(f"❌ 作用域管理测试失败: {e}")

def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")
    
    vm = VBCVirtualMachine()
    
    # 测试访问未初始化的局部变量
    bytecode = [
        (Opcode.LOAD_LOCAL_VAR, 5),   # 尝试访问未初始化的局部变量
        (Opcode.HALT,)
    ]
    
    constants = []
    
    try:
        vm.excute(bytecode, constants)
        print("❌ 错误处理测试失败: 应该抛出异常")
    except RuntimeError as e:
        if "未初始化" in str(e):
            print("✅ 错误处理测试成功: 正确检测到未初始化变量")
        else:
            print(f"❌ 错误处理测试失败: 异常信息不正确 - {e}")
    except Exception as e:
        print(f"❌ 错误处理测试失败: 异常类型不正确 - {e}")

if __name__ == "__main__":
    print("开始测试变量操作类指令实现")
    
    test_local_variables()
    test_global_variables()
    test_scope_management()
    test_error_handling()
    
    print("\n测试完成！")
