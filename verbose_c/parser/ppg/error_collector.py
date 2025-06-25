from typing import List, Optional, Set, Tuple
from dataclasses import dataclass
from verbose_c.parser.lexer.enum import Operator, TokenType
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
    
    def _get_context(self, line: int, column: int) -> List[Tuple[int, str]]:
        """获取错误位置的上下文"""
        context_lines = []
        for i in range(max(1, line - 2), min(len(self.tokenizer._source_lines), line + 2) + 1):
            context_lines.append((i, self.tokenizer.get_line_source(i)))
        return context_lines
    
    def get_best_error(self) -> Optional[ParseError]:
        """获取最远位置的错误"""
        if not self.errors:
            return None
            
        return max(self.errors, key=lambda e: e.position)
    
    def format_error_report(self) -> str:
        """格式化错误报告"""
        if not self.errors:
            return "没有发现解析错误"
        
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
            # 如果找不到有效token，就用peek的结果
            actual_token_at_furthest = self.tokenizer.peek()

        line = actual_token_at_furthest.line or 0
        column = actual_token_at_furthest.column or 0

        context_lines_with_numbers = self._get_context(line, column)

        lines = []        
        lines.append(f"错误位置: 第 {line} 行，第 {column} 列")
        
        if self.furthest_expected:
            expected_set = self.furthest_expected
            expected_str = ', '.join(sorted(expected_set))

            lines.append(f"错误: 期望 {expected_str} 其中之一, 实际是 '{actual_token_at_furthest.string}'")
        else:
            lines.append(f"错误: 在 '{actual_token_at_furthest.string}' 处遇到未知语法错误")

        if context_lines_with_numbers:
            lines.append("\n错误上下文:")
            max_lineno_width = len(str(context_lines_with_numbers[-1][0]))
            for lineno, line_content in context_lines_with_numbers:
                lines.append(f"  {lineno:>{max_lineno_width}} | {line_content}")
                if lineno == line:
                    padding = 2 + max_lineno_width + 3 + column
                    indicator = ' ' * padding + '^' * len(actual_token_at_furthest.string)
                    lines.append(indicator)

        best_error = self.get_best_error()
        if best_error and best_error.rule_stack:
            lines.append(f"\n规则调用栈:\n {' -> '.join(best_error.rule_stack)}")

        lines.append("\n" + "=" * 50)
        return '\n'.join(lines)
