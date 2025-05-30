import contextlib
from abc import abstractmethod
from typing import Any, IO, AbstractSet, Iterator, Optional, Text

from verbose_c.parser.ppg import sccutils
from verbose_c.parser.ppg.grammar import (
    Alt,
    Cut,
    Forced,
    Gather,
    Grammar,
    GrammarError,
    GrammarVisitor,
    Group,
    Lookahead,
    NamedItem,
    NameLeaf,
    Opt,
    Plain,
    Repeat0,
    Repeat1,
    Rhs,
    Rule,
    StringLeaf,
)


class RuleCheckingVisitor(GrammarVisitor):
    def __init__(self, rules: dict[str, Rule], tokens: set[str]):
        self.rules = rules
        self.tokens = tokens

    def visit_NameLeaf(self, node: NameLeaf) -> None:
        if node.value not in self.rules and node.value not in self.tokens:
            # TODO: 为（叶子）节点添加行/列信息
            raise GrammarError(f"悬空引用规则 {node.value!r}")

    def visit_NamedItem(self, node: NamedItem) -> None:
        if node.name and node.name.startswith("_"):
            raise GrammarError(f"变量名不能以下划线开头: '{node.name}'")
        self.visit(node.item)


class ParserGenerator:
    callmakervisitor: GrammarVisitor

    def __init__(self, grammar: Grammar, tokens: set[str], file: Optional[IO[Text]]):
        self.grammar = grammar
        self.tokens = tokens
        self.rules = grammar.rules
        self.validate_rule_names()
        if "trailer" not in grammar.metas and "start" not in self.rules:
            raise GrammarError("没有 trailer 的语法必须有 'start' 规则")
        checker = RuleCheckingVisitor(self.rules, self.tokens)
        for rule in self.rules.values():
            checker.visit(rule)
        self.file = file
        self.level = 0
        compute_nullables(self.rules)
        self.first_graph, self.first_sccs = compute_left_recursives(self.rules)
        self.todo = self.rules.copy()  # 需要生成的规则
        self.counter = 0  # 用于 name_rule()/name_loop() 的计数器
        self.all_rules: dict[str, Rule] = {}  # 规则 + 临时规则
        self._local_variable_stack: list[list[str]] = []

    def validate_rule_names(self) -> None:
        for rule in self.rules:
            if rule.startswith("_"):
                raise GrammarError(f"规则名不能以下划线开头: '{rule}'")

    @contextlib.contextmanager
    def local_variable_context(self) -> Iterator[None]:
        self._local_variable_stack.append([])
        yield
        self._local_variable_stack.pop()

    @property
    def local_variable_names(self) -> list[str]:
        return self._local_variable_stack[-1]

    @abstractmethod
    def generate(self, filename: str) -> None:
        raise NotImplementedError

    @contextlib.contextmanager
    def indent(self) -> Iterator[None]:
        self.level += 1
        try:
            yield
        finally:
            self.level -= 1

    def print(self, *args: object) -> None:
        if not args:
            print(file=self.file)
        else:
            print("    " * self.level, end="", file=self.file)
            print(*args, file=self.file)

    def printblock(self, lines: str) -> None:
        for line in lines.splitlines():
            self.print(line)

    def collect_todo(self) -> None:
        done: set[str] = set()
        while True:
            alltodo = list(self.todo)
            self.all_rules.update(self.todo)
            todo = [i for i in alltodo if i not in done]
            if not todo:
                break
            for rulename in todo:
                self.todo[rulename].collect_todo(self)
            done = set(alltodo)

    def artificial_rule_from_rhs(self, rhs: Rhs) -> str:
        self.counter += 1
        name = f"_tmp_{self.counter}"  # TODO: 取一个更好的名字。
        self.todo[name] = Rule(name, None, rhs)
        return name

    def artificial_rule_from_repeat(self, node: Plain, is_repeat1: bool) -> str:
        self.counter += 1
        if is_repeat1:
            prefix = "_loop1_"
        else:
            prefix = "_loop0_"
        name = f"{prefix}{self.counter}"  # TODO: 通过名字传递信息不太优雅。
        self.todo[name] = Rule(name, None, Rhs([Alt([NamedItem(None, node)])]))
        return name

    def artificial_rule_from_gather(self, node: Gather) -> str:
        self.counter += 1
        name = f"_gather_{self.counter}"
        self.counter += 1
        extra_function_name = f"_loop0_{self.counter}"
        extra_function_alt = Alt(
            [NamedItem(None, node.separator), NamedItem("elem", node.node)],
            action="elem",
        )
        self.todo[extra_function_name] = Rule(
            extra_function_name,
            None,
            Rhs([extra_function_alt]),
        )
        alt = Alt(
            [NamedItem("elem", node.node), NamedItem("seq", NameLeaf(extra_function_name))],
        )
        self.todo[name] = Rule(
            name,
            None,
            Rhs([alt]),
        )
        return name

    def dedupe(self, name: str) -> str:
        origname = name
        counter = 0
        while name in self.local_variable_names:
            counter += 1
            name = f"{origname}_{counter}"
        self.local_variable_names.append(name)
        return name


class NullableVisitor(GrammarVisitor):
    def __init__(self, rules: dict[str, Rule]) -> None:
        self.rules = rules
        self.visited: set[Any] = set()

    def visit_Rule(self, rule: Rule) -> bool:
        if rule in self.visited:
            return False
        self.visited.add(rule)
        if self.visit(rule.rhs):
            rule.nullable = True
        return rule.nullable

    def visit_Rhs(self, rhs: Rhs) -> bool:
        for alt in rhs.alts:
            if self.visit(alt):
                return True
        return False

    def visit_Alt(self, alt: Alt) -> bool:
        for item in alt.items:
            if not self.visit(item):
                return False
        return True

    def visit_Forced(self, force: Forced) -> bool:
        return True

    def visit_LookAhead(self, lookahead: Lookahead) -> bool:
        return True

    def visit_Opt(self, opt: Opt) -> bool:
        return True

    def visit_Repeat0(self, repeat: Repeat0) -> bool:
        return True

    def visit_Repeat1(self, repeat: Repeat1) -> bool:
        return False

    def visit_Gather(self, gather: Gather) -> bool:
        return False

    def visit_Cut(self, cut: Cut) -> bool:
        return False

    def visit_Group(self, group: Group) -> bool:
        return self.visit(group.rhs)

    def visit_NamedItem(self, item: NamedItem) -> bool:
        if self.visit(item.item):
            item.nullable = True
        return item.nullable

    def visit_NameLeaf(self, node: NameLeaf) -> bool:
        if node.value in self.rules:
            return self.visit(self.rules[node.value])
        # Token 或未知；永远不为空。
        return False

    def visit_StringLeaf(self, node: StringLeaf) -> bool:
        # 字符串 token '' 被认为是空。
        return not node.value


def compute_nullables(rules: dict[str, Rule]) -> None:
    nullable_visitor = NullableVisitor(rules)
    for rule in rules.values():
        nullable_visitor.visit(rule)


def compute_left_recursives(
    rules: dict[str, Rule]
) -> tuple[dict[str, AbstractSet[str]], list[AbstractSet[str]]]:
    graph = make_first_graph(rules)
    sccs = list(sccutils.strongly_connected_components(graph.keys(), graph))
    for scc in sccs:
        if len(scc) > 1:
            for name in scc:
                rules[name].left_recursive = True
            # 尝试找到一个领导者，使所有环路都经过它。
            leaders = set(scc)
            for start in scc:
                for cycle in sccutils.find_cycles_in_scc(graph, scc, start):
                    # print("Cycle:", " -> ".join(cycle))
                    leaders -= scc - set(cycle)
                    if not leaders:
                        raise ValueError(
                            f"强连通分量 {scc} 没有领导候选者（没有元素包含在所有环路中）"
                        )
            # print("Leaders:", leaders)
            leader = min(leaders)  # 从候选者中任意选择一个领导者。
            rules[leader].leader = True
        else:
            name = min(scc)  # 唯一的元素。
            if name in graph[name]:
                rules[name].left_recursive = True
                rules[name].leader = True
    return graph, sccs


def make_first_graph(rules: dict[str, Rule]) -> dict[str, AbstractSet[str]]:
    """计算左侧调用的图。

    如果 A 在初始位置可能调用 B，则从 A 到 B 有一条边。

    注意，这需要先计算可空标志。
    """
    graph = {}
    vertices: set[str] = set()
    for rulename, rhs in rules.items():
        graph[rulename] = names = rhs.initial_names()
        vertices |= names
    for vertex in vertices:
        graph.setdefault(vertex, set())
    return graph
