from typing import List, Optional, Set
from dataclasses import dataclass
from verbose_c.error import DiagnosticEntry, DiagnosticReport
from verbose_c.error.format import format_report
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.token import Token
from verbose_c.parser.lexer.tokenizer import Mark, Tokenizer

@dataclass
class ParseError:
    """解析错误信息"""
    position: Mark
    line: int
    column: int
    message: str
    expected_tokens: Set[str]
    actual_token: Optional[Token]
    rule_stack: List[str]

class ErrorCollector:
    """错误收集器"""
    
    def __init__(self, tokenizer):
        self.tokenizer: Tokenizer = tokenizer
        self.errors: List[ParseError] = []
        self.furthest_position: Mark = 0
        self.furthest_expected: Set[str] = set()
        self.rule_stack: List[str] = []
        
    def enter_rule(self, rule_name: str):
        """进入规则"""
        self.rule_stack.append(rule_name)
        
    def exit_rule(self, rule_name: str):
        """退出规则"""
        if self.rule_stack and self.rule_stack[-1] == rule_name:
            self.rule_stack.pop()
    
    def record_expectation(self, position: Mark, expected: str):
        """记录期望的token"""
        if position > self.furthest_position:
            self.furthest_position = position
            self.furthest_expected = {expected}
        elif position == self.furthest_position:
            self.furthest_expected.add(expected)
    
    def add_error(self, position: Mark, message: str, expected_tokens: Set[str] = None):
        """添加错误"""
        if expected_tokens is None:
            expected_tokens = set()
            
        current_token = self.tokenizer.peek()
        
        error = ParseError(
            position=position,
            line=current_token.line or 0,
            column=current_token.column or 0,
            message=message,
            expected_tokens=expected_tokens,
            actual_token=current_token,
            rule_stack=self.rule_stack.copy()
        )
        
        self.errors.append(error)
    
    def get_best_error(self) -> Optional[ParseError]:
        """获取最远位置的错误"""
        if not self.errors:
            return None
            
        return max(self.errors, key=lambda e: e.position)
    
    def get_report(self) -> DiagnosticReport | None:
        """收集最远失败位置的结构化诊断。

        Returns:
            包含实际文件、源码上下文及规则栈的报告；无错误时返回 None。
        """
        if not self.errors:
            return None
        
        # 从最远的位置开始，查找第一个有效token作为错误报告的目标
        peek_index = self.furthest_position
        actual_token_at_furthest = None
        while peek_index < len(self.tokenizer.tokens):
            tok = self.tokenizer.tokens[peek_index]
            if tok.type not in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.WHITESPACE):
                actual_token_at_furthest = tok
                break
            peek_index += 1
        
        if actual_token_at_furthest is None:
            actual_token_at_furthest = self.tokenizer.tokens[-1]

        line = actual_token_at_furthest.line
        column = actual_token_at_furthest.column
        path = actual_token_at_furthest.path or self.tokenizer.lexer.filename
        actual = "EOF" if actual_token_at_furthest.type == TokenType.END else actual_token_at_furthest.string
        if self.furthest_expected:
            message = f"期望 {', '.join(sorted(self.furthest_expected))} 其中之一, 实际是 {actual!r}"
        else:
            message = f"在 {actual!r} 处遇到未知语法错误"
        context = self.tokenizer.source_manager.get_context(path, line)
        if (actual_token_at_furthest.type == TokenType.END and column == 0
                and line is not None and self.tokenizer.lexer.source.endswith("\n")):
            # SourceManager 不保存末尾空行，EOF 指示仍需落在实际终止位置。
            context.append((line, ""))
        best_error = self.get_best_error()
        return DiagnosticReport("解析错误", [DiagnosticEntry(
            message, filepath=path, line=line, column=column,
            source_context=context,
            highlight_length=1 if actual_token_at_furthest.type == TokenType.END else max(1, len(actual)),
            expected_tokens=sorted(self.furthest_expected), actual_token=actual,
            rule_stack=best_error.rule_stack.copy() if best_error else [],
        )])

    def format_error_report(self) -> str:
        """保留字符串接口，正文统一交给错误包渲染。"""
        report = self.get_report()
        return format_report(report) if report is not None else "没有发现解析错误"
