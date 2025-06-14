import ast
from datetime import datetime
import re
import token
from typing import IO, Any, Dict, List, Optional, Sequence, Set, Text, Tuple

from verbose_c.parser.ppg import grammar
from verbose_c.parser.ppg.grammar import (
    Alt,
    Cut,
    Forced,
    Gather,
    GrammarVisitor,
    Group,
    Lookahead,
    NamedItem,
    NameLeaf,
    NegativeLookahead,
    Opt,
    PositiveLookahead,
    Repeat0,
    Repeat1,
    Rhs,
    Rule,
    StringLeaf,
)
from verbose_c.parser.ppg.parser_generator import ParserGenerator
from verbose_c.parser.lexer.enum import TokenType

MODULE_PREFIX = """\
#!/usr/bin/env python3.8
# 从 {filename} 文件生成，用于处理 verbose-c 语法
# 生成于 {datetime}

import sys

from typing import Any

# TODO: 可能需要根据实际情况动态修改
from verbose_c.parser.parser.ast.node import *
from verbose_c.parser.parser.parser import memoize, memoize_left_rec, logger, Parser
from verbose_c.parser.lexer.enum import Operator
"""

MODULE_SUFFIX = """
if __name__ == '__main__':
    print("通过实例化 {class_name} 使用")
"""


class InvalidNodeVisitor(GrammarVisitor):
    def visit_NameLeaf(self, node: NameLeaf) -> bool:
        name = node.value
        return name.startswith("invalid")

    def visit_StringLeaf(self, node: StringLeaf) -> bool:
        return False

    def visit_NamedItem(self, node: NamedItem) -> bool:
        return self.visit(node.item)

    def visit_Rhs(self, node: Rhs) -> bool:
        return any(self.visit(alt) for alt in node.alts)

    def visit_Alt(self, node: Alt) -> bool:
        return any(self.visit(item) for item in node.items)

    def lookahead_call_helper(self, node: Lookahead) -> bool:
        return self.visit(node.node)

    def visit_PositiveLookahead(self, node: PositiveLookahead) -> bool:
        return self.lookahead_call_helper(node)

    def visit_NegativeLookahead(self, node: NegativeLookahead) -> bool:
        return self.lookahead_call_helper(node)

    def visit_Opt(self, node: Opt) -> bool:
        return self.visit(node.node)

    def visit_Repeat(self, node: Repeat0) -> Tuple[str, str]:
        return self.visit(node.node)

    def visit_Gather(self, node: Gather) -> Tuple[str, str]:
        return self.visit(node.node)

    def visit_Group(self, node: Group) -> bool:
        return self.visit(node.rhs)

    def visit_Cut(self, node: Cut) -> bool:
        return False

    def visit_Forced(self, node: Forced) -> bool:
        return self.visit(node.node)


class PythonCallMakerVisitor(GrammarVisitor):
    def __init__(self, parser_generator: ParserGenerator):
        self.gen = parser_generator
        self.cache: Dict[Any, Any] = {}
        self.keywords: Set[str] = set()
        self.soft_keywords: Set[str] = set()

    def visit_NameLeaf(self, node: NameLeaf) -> Tuple[Optional[str], str]:
        name = node.value
        if name == "SOFT_KEYWORD":
            return "soft_keyword", "self.soft_keyword()"
        if name in (
            "NAME",
            "NUMBER",
            "STRING",
            "INCLUDE_HEADER",
            "OP",
            "TYPE_COMMENT",
        ):
            name = name.lower()
            return name, f"self.{name}()"
        if name in ("NEWLINE", "DEDENT", "INDENT", "END", "ASYNC", "AWAIT"):
            # Avoid using names that can be Python keywords
            return "_" + name.lower(), f"self.expect({name!r})"
        return name, f"self.{name}()"

    def visit_StringLeaf(self, node: StringLeaf) -> Tuple[str, str]:
        val = ast.literal_eval(node.value)
        if re.match(r"[a-zA-Z_]\w*\Z", val):  # This is a keyword
            if node.value.endswith("'"):
                self.keywords.add(val)
            else:
                self.soft_keywords.add(val)
        return "literal", f"self.expect({node.value})"

    def visit_Rhs(self, node: Rhs) -> Tuple[Optional[str], str]:
        if node in self.cache:
            return self.cache[node]
        if len(node.alts) == 1 and len(node.alts[0].items) == 1:
            self.cache[node] = self.visit(node.alts[0].items[0])
        else:
            name = self.gen.artificial_rule_from_rhs(node)
            self.cache[node] = name, f"self.{name}()"
        return self.cache[node]

    def visit_NamedItem(self, node: NamedItem) -> Tuple[Optional[str], str]:
        name, call = self.visit(node.item)
        if node.name:
            name = node.name
        return name, call

    def lookahead_call_helper(self, node: Lookahead) -> Tuple[str, str]:
        name, call = self.visit(node.node)
        head, tail = call.split("(", 1)
        assert tail[-1] == ")"
        tail = tail[:-1]
        return head, tail

    def visit_PositiveLookahead(self, node: PositiveLookahead) -> Tuple[None, str]:
        head, tail = self.lookahead_call_helper(node)
        return None, f"self.positive_lookahead({head}, {tail})"

    def visit_NegativeLookahead(self, node: NegativeLookahead) -> Tuple[None, str]:
        head, tail = self.lookahead_call_helper(node)
        return None, f"self.negative_lookahead({head}, {tail})"

    def visit_Opt(self, node: Opt) -> Tuple[str, str]:
        name, call = self.visit(node.node)
        # Note trailing comma (the call may already have one comma
        # at the end, for example when rules have both repeat0 and optional
        # markers, e.g: [rule*])
        if call.endswith(","):
            return "opt", call
        else:
            return "opt", f"{call},"

    def visit_Repeat0(self, node: Repeat0) -> Tuple[str, str]:
        if node in self.cache:
            return self.cache[node]
        name = self.gen.artificial_rule_from_repeat(node.node, False)
        self.cache[node] = name, f"self.{name}(),"  # Also a trailing comma!
        return self.cache[node]

    def visit_Repeat1(self, node: Repeat1) -> Tuple[str, str]:
        if node in self.cache:
            return self.cache[node]
        name = self.gen.artificial_rule_from_repeat(node.node, True)
        self.cache[node] = name, f"self.{name}()"  # But no trailing comma here!
        return self.cache[node]

    def visit_Gather(self, node: Gather) -> Tuple[str, str]:
        if node in self.cache:
            return self.cache[node]
        name = self.gen.artificial_rule_from_gather(node)
        self.cache[node] = name, f"self.{name}()"  # No trailing comma here either!
        return self.cache[node]

    def visit_Group(self, node: Group) -> Tuple[Optional[str], str]:
        return self.visit(node.rhs)

    def visit_Cut(self, node: Cut) -> Tuple[str, str]:
        return "cut", "True"

    def visit_Forced(self, node: Forced) -> Tuple[str, str]:
        if isinstance(node.node, Group):
            _, val = self.visit(node.node.rhs)
            return "forced", f"self.expect_forced({val}, '''({node.node.rhs!s})''')"
        else:
            return (
                "forced",
                f"self.expect_forced(self.expect({node.node.value}), {node.node.value!r})",
            )


class UsedNamesVisitor(ast.NodeVisitor):
    def generic_visit(self, node: ast.AST) -> Set[str]:
        result = set()
        for _, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        result.update(self.visit(item))
            elif isinstance(value, ast.AST):
                result.update(self.visit(value))
        return result

    def visit_Name(self, node: ast.Name) -> Set[str]:
        return {node.id}


class PythonParserGenerator(ParserGenerator, GrammarVisitor):
    def __init__(
        self,
        grammar: grammar.Grammar,
        file: Optional[IO[Text]],
        tokens: Set[str] = set([member.name for member in TokenType]),
        location_formatting: Optional[str] = None,
        unreachable_formatting: Optional[str] = None,
    ):
        tokens.add("SOFT_KEYWORD")
        super().__init__(grammar, tokens, file)
        self.callmakervisitor: PythonCallMakerVisitor = PythonCallMakerVisitor(self)
        self.invalidvisitor: InvalidNodeVisitor = InvalidNodeVisitor()
        self.usednamesvisitor: UsedNamesVisitor = UsedNamesVisitor()
        self.unreachable_formatting = unreachable_formatting or "None  # pragma: no cover"
        self.location_formatting = (
            location_formatting
            or "start_line=start_line, start_column=start_column, "
            "end_line=end_line, end_column=end_column"
        )
        self.cleanup_statements: List[str] = []

    def generate(self, filename: str) -> None:
        header = self.grammar.metas.get("header", MODULE_PREFIX)
        if header is not None:
            self.print(header.rstrip("\n").format(filename=filename, datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        subheader = self.grammar.metas.get("subheader", "")
        if subheader:
            self.print(subheader)
        cls_name = self.grammar.metas.get("class", "GeneratedParser")
        self.print("# Keywords and soft keywords are listed at the end of the parser definition.")
        self.print(f"class {cls_name}(Parser):")
        while self.todo:
            for rulename, rule in list(self.todo.items()):
                del self.todo[rulename]
                self.print()
                with self.indent():
                    self.visit(rule)

        self.print()
        with self.indent():
            self.print(f"KEYWORDS = {tuple(sorted(self.callmakervisitor.keywords))}")
            self.print(f"SOFT_KEYWORDS = {tuple(sorted(self.callmakervisitor.soft_keywords))}")

        trailer = self.grammar.metas.get("trailer", MODULE_SUFFIX.format(class_name=cls_name))
        if trailer is not None:
            self.print(trailer.rstrip("\n"))

    def alts_uses_locations(self, alts: Sequence[Alt]) -> bool:
        for alt in alts:
            if alt.action and "LOCATIONS" in alt.action:
                return True
            for n in alt.items:
                if isinstance(n.item, Group) and self.alts_uses_locations(n.item.rhs.alts):
                    return True
        return False

    def add_return(self, ret_val: str) -> None:
        for stmt in self.cleanup_statements:
            self.print(stmt)
        self.print(f"return {ret_val}")

    def visit_Rule(self, node: Rule) -> None:
        is_loop = node.is_loop()
        is_gather = node.is_gather()
        rhs = node.flatten()
        if node.left_recursive:
            if node.leader:
                self.print("@memoize_left_rec")
            else:
                # Non-leader rules in a cycle are not memoized,
                # but they must still be logged.
                self.print("@logger")
        else:
            self.print("@memoize")
        node_type = node.type or "Any"
        self.print(f"def {node.name}(self) -> {node_type} | None:")
        with self.indent():
            self.print(f"# {node.name}: {rhs}")
            if node.nullable:
                self.print(f"# nullable={node.nullable}")

            if node.name.endswith("without_invalid"):
                self.print("_prev_call_invalid = self.call_invalid_rules")
                self.print("self.call_invalid_rules = False")
                self.cleanup_statements.append("self.call_invalid_rules = _prev_call_invalid")

            self.print("mark = self._mark()")
            if self.alts_uses_locations(node.rhs.alts):
                self.print("tok = self._tokenizer.peek()")
                self.print("start_line = tok.line")
                self.print("start_column = tok.column")
            if is_loop:
                self.print("children = []")
            self.visit(rhs, is_loop=is_loop, is_gather=is_gather)
            if is_loop:
                self.add_return("children")
            else:
                self.add_return("None")

        if node.name.endswith("without_invalid"):
            self.cleanup_statements.pop()

    def visit_NamedItem(
        self, node: NamedItem, used: Optional[Set[str]], unreachable: bool
    ) -> None:
        name, call = self.callmakervisitor.visit(node.item)
        if unreachable:
            name = None
        elif node.name:
            name = node.name

        if used is not None and name not in used:
            name = None

        if not name:
            # Parentheses are needed because the trailing comma may appear :>
            self.print(f"({call})")
        else:
            if name != "cut":
                name = self.dedupe(name)
            self.print(f"({name} := {call})")

    def visit_Rhs(self, node: Rhs, is_loop: bool = False, is_gather: bool = False) -> None:
        if is_loop:
            assert len(node.alts) == 1
        for alt in node.alts:
            self.visit(alt, is_loop=is_loop, is_gather=is_gather)

    def print_action(
        self,
        action: Optional[str],
        locations: bool,
        unreachable: bool,
        is_gather: bool,
        is_loop: bool,
        has_invalid: bool,
    ) -> None:
        if not action:
            if is_gather:
                assert len(self.local_variable_names) == 2
                action = f"[{self.local_variable_names[0]}] + {self.local_variable_names[1]}"
            else:
                if has_invalid:
                    assert unreachable
                    assert isinstance(action, str)  # for type checker
                elif len(self.local_variable_names) == 1:
                    action = f"{self.local_variable_names[0]}"
                else:
                    action = f"[{', '.join(self.local_variable_names)}]"

        if locations:
            self.print("tok = self._tokenizer.get_last_non_whitespace_token()")
            self.print("end_line = tok.line")
            self.print("end_column = tok.column")
        if is_loop:
            self.print(f"children.append({action})")
            self.print("mark = self._mark()")
        else:
            self.add_return(f"{action}")

    def visit_Alt(self, node: Alt, is_loop: bool, is_gather: bool) -> None:
        has_cut = any(isinstance(item.item, Cut) for item in node.items)
        has_invalid = self.invalidvisitor.visit(node)

        action = node.action
        if not action and not is_gather and has_invalid:
            action = "UNREACHABLE"

        locations = False
        unreachable = False
        used = None
        if action:
            # Replace magic name in the action rule
            if "LOCATIONS" in action:
                locations = True
                action = action.replace("LOCATIONS", self.location_formatting)
            if "UNREACHABLE" in action:
                unreachable = True
                action = action.replace("UNREACHABLE", self.unreachable_formatting)

            # Extract the names actually used in the action.
            used = self.usednamesvisitor.visit(ast.parse(action))
            if has_cut:
                used.add("cut")

        with self.local_variable_context():
            if has_cut:
                self.print("cut = False")
            if is_loop:
                self.print("while (")
            else:
                self.print("if (")
            with self.indent():
                first = True
                if has_invalid:
                    self.print("self.call_invalid_rules")
                    first = False
                for item in node.items:
                    if first:
                        first = False
                    else:
                        self.print("and")
                    self.visit(item, used=used, unreachable=unreachable)
                    if is_gather:
                        self.print("is not None")

            self.print("):")
            with self.indent():
                # flake8 complains that visit_Alt is too complicated, so here we are :P
                self.print_action(action, locations, unreachable, is_gather, is_loop, has_invalid)

            self.print("self._reset(mark)")
            # Skip remaining alternatives if a cut was reached.
            if has_cut:
                self.print("if cut:")
                with self.indent():
                    self.add_return("None")
