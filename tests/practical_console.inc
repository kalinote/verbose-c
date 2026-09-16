#ifndef PRACTICAL_CONSOLE_INC
#define PRACTICAL_CONSOLE_INC

// 共用数字输入输出，避免依赖尚未支持的 printf 或字符串下标。
int decimal_digit(string token) {
    if (token == "0") { return 0; }
    if (token == "1") { return 1; }
    if (token == "2") { return 2; }
    if (token == "3") { return 3; }
    if (token == "4") { return 4; }
    if (token == "5") { return 5; }
    if (token == "6") { return 6; }
    if (token == "7") { return 7; }
    if (token == "8") { return 8; }
    if (token == "9") { return 9; }
    return -1;
}

// 读取一个有符号 32 位整数；空白分隔，非法输入以退出码 2 结束。
int read_integer() {
    string token = read(STDIN, 1);
    while (token == " " || token == "\t" || token == "\r" || token == "\n") {
        token = read(STDIN, 1);
    }
    bool negative = token == "-";
    if (negative || token == "+") {
        token = read(STDIN, 1);
    }
    int last_digit = 7;
    if (negative) { last_digit = 8; }
    int value = 0;
    int digits = 0;
    while (token != "" && token != " " && token != "\t" && token != "\r" && token != "\n") {
        int digit = decimal_digit(token);
        if (digit < 0) {
            write(STDERR, "输入错误：需要十进制整数。\n");
            exit(2);
        }
        // 以负数累积，使 -2147483648 也能被正确读取。
        if (value < -214748364 || (value == -214748364 && digit > last_digit)) {
            write(STDERR, "输入错误：整数超出 32 位范围。\n");
            exit(2);
        }
        value = value * 10 - digit;
        digits = digits + 1;
        token = read(STDIN, 1);
    }
    if (digits == 0) {
        write(STDERR, "输入错误：缺少整数。\n");
        exit(2);
    }
    if (negative) { return value; }
    return -value;
}

// 递归输出非正数的各位，保持 long 最小值的输出安全。
void print_negative_digits(long value) {
    if (value <= -10) {
        print_negative_digits(value / 10);
    }
    int digit = (int)(-(value % 10));
    switch (digit) {
        case 0: write(STDOUT, "0"); break;
        case 1: write(STDOUT, "1"); break;
        case 2: write(STDOUT, "2"); break;
        case 3: write(STDOUT, "3"); break;
        case 4: write(STDOUT, "4"); break;
        case 5: write(STDOUT, "5"); break;
        case 6: write(STDOUT, "6"); break;
        case 7: write(STDOUT, "7"); break;
        case 8: write(STDOUT, "8"); break;
        case 9: write(STDOUT, "9"); break;
    }
}

// 输出完整 64 位整数，不经浮点转换。
void print_integer(long value) {
    if (value < 0) {
        write(STDOUT, "-");
    } else {
        value = -value;
    }
    print_negative_digits(value);
}

// 将非负的百分之一单位格式化为两位小数。
void print_fixed2(long hundredths) {
    print_integer(hundredths / 100);
    write(STDOUT, ".");
    long remainder = hundredths % 100;
    if (remainder < 10) { write(STDOUT, "0"); }
    print_integer(remainder);
}

#endif
