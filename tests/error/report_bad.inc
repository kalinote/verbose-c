// 被包含文件：第 5 行故意写成非法语法，用于验证多文件报错上下文。

int imported_value() {
    return 42
    int broken = ;   // 缺少分号 + 非法表达式，解析器应在此报错
}
