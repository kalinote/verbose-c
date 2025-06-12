# verbose-c

自己动手实现一个类C语言语法解释器，用于学习目的

## 安装依赖环境
使用 Python 3.13 及以上版本

```bash
pip install -r requirement.txt
```

## 运行方法
```bash
python -m verbose_c.cli .\test.vrbc 
```

## 编译方法
```bash
nuitka .\verbose_c\cli.py --follow-imports --standalone
```
