from enum import Enum, auto

class TokenType(Enum):
    """
    Token枚举，后续改成通过配置文件配置
    """
    # 空白符和注释
    WHITESPACE = ("WHITESPACE", r"[ \t\f\v]+")                 # 空白符（不包括换行）
    COMMENT    = ("COMMENT", r"//.*|/\*[\s\S]*?\*/")    # 单行和多行注释
    NEWLINE    = ("NEWLINE", r"\r?\n")                          # 换行符

    # 预处理器相关或特殊构造
    MACRO_CODE = ("MACRO_CODE", r"#(?:[^\r\n]*?\\\r?\n)*[^\r\n]*") # 宏代码, 匹配从#开始的完整预处理指令，支持'\'换行

    # 复合操作符
    SHIFT_LEFT_ASSIGN = ("<<=", r"<<=")                 # 左移等于
    SHIFT_RIGHT_ASSIGN = (">>=", r">>=")                # 右移等于
    
    ARROW      = ("->", r"->")                          # 箭头操作符
    INCREMENT  = ("++", r"\+\+")                        # 自增
    DECREMENT  = ("--", r"--")                          # 自减
    
    PLUS_ASSIGN = ("+=", r"\+=")                        # 加等于
    MINUS_ASSIGN = ("-=", r"-=")                        # 减等于
    STAR_ASSIGN = ("*=", r"\*=")                        # 乘等于
    SLASH_ASSIGN = ("/=", r"/=")                        # 除等于
    PERCENT_ASSIGN = ("%=", r"%=")                      # 模等于
    AND_ASSIGN = ("&=", r"&=")                          # 与等于
    OR_ASSIGN  = ("|=", r"\|=")                         # 或等于
    XOR_ASSIGN = ("^=", r"\^=")                         # 异或等于
    
    EQUAL      = ("==", r"==")                          # 等于
    NOT_EQUAL  = ("!=", r"!=")                          # 不等于
    LESS_EQUAL = ("<=", r"<=")                          # 小于等于
    GREATER_EQUAL = (">=", r">=")                       # 大于等于
    AND        = ("&&", r"&&")                          # 逻辑与
    OR         = ("||", r"\|\|")                        # 逻辑或
    SHIFT_LEFT = ("<<", r"<<")                          # 左移
    SHIFT_RIGHT = (">>", r">>")                         # 右移
    ELLIPSES    = ("...", r"\.\.\.")                    # 省略号

    # 单字符操作符
    PLUS       = ("+", r"\+")                           # 加号
    MINUS      = ("-", r"-")                            # 减号
    STAR       = ("*", r"\*")                           # 星号
    SLASH      = ("/", r"/")                            # 斜杠
    PERCENT    = ("%", r"%")                            # 百分号
    ASSIGN     = ("=", r"=")                            # 赋值
    LESS       = ("<", r"<")                            # 小于
    GREATER    = (">", r">")                            # 大于
    NOT        = ("!", r"!")                            # 逻辑非
    BIT_AND    = ("&", r"&")                            # 按位与
    BIT_OR     = ("|", r"\|")                           # 按位或
    BIT_XOR    = ("^", r"\^")                           # 按位异或
    BIT_NOT    = ("~", r"~")                            # 按位取反
    DOT        = (".", r"\.")                           # 点操作符
    QUESTION   = ("?", r"\?")                           # 问号
    COLON      = (":", r":")                            # 冒号
    AT         = ("@", r"@")                            # 符号@

    # 字面量和标识符
    STRING     = ("STRING", r""""(?:\\.|[^"\\])*"|'(?:\\.|[^\\'])*'""")  # 字符串和字符字面量
    NUMBER     = ("NUMBER", r"(?:0[xX][0-9a-fA-F]+|0[0-7]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")  # 整数、浮点数、八进制、十六进制
    NAME       = ("NAME", r"[^\d\W][\w]*")    # 标识符 (关键字通过后处理识别)
    
    # 分隔符和标点符号
    SEMICOLON  = (";", r";")                            # 分号
    COMMA      = (",", r",")                            # 逗号
    LPAREN     = ("(", r"\(")                           # 左括号
    RPAREN     = (")", r"\)")                           # 右括号
    LBRACK     = ("[", r"\[")                           # 左方括号
    RBRACK     = ("]", r"\]")                           # 右方括号
    LBRACE     = ("{", r"\{")                           # 左花括号
    RBRACE     = ("}", r"\}")                           # 右花括号
    
    # 特殊标记
    UNKNOWN    = ("UNKNOWN", r".")                      # 未知字符 (必须在所有其他实际token之后)
    END        = ("END", r"$^")                         # 结束标记 (模式不匹配任何内容，由词法分析器在末尾添加)
    
    # 预留
    INDENT     = ("INDENT", r"$^")                    # 缩进
    DEDENT     = ("DEDENT", r"$^")                    # 去缩进
    
    def __init__(self, literal, pattern):
        self._literal: str = literal
        self._pattern: str = pattern

    @property
    def literal(self):
        return self._literal

    @property
    def pattern(self):
        return self._pattern
    
    def __repr__(self) -> str:
        return f"TokenType(literal={self.literal}, pattern={self.pattern})"

    @classmethod
    def from_literal(cls, literal):
        if cls._literal_map is None:
            cls._literal_map = {member.literal: member for member in cls}
        try:
            return cls._literal_map[literal]
        except KeyError:
            return None
    
TokenType._literal_map = {}

class Operator(Enum):
    """
    Operator 枚举类
    用于定义支持的操作符类型，便于后续表达式解析和判断。
    """
    EQUAL = "=="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    GREATER_THAN = ">"
    LESS_EQUAL = "<="
    GREATER_EQUAL = ">="
    LOGICAL_AND = "&&"
    LOGICAL_OR = "||"
    ASSIGN = "="
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"
    NOT = "!"

    def __str__(self):
        return self.value 

    def __repr__(self) -> str:
        return f"Operator(value='{self.value}')"
