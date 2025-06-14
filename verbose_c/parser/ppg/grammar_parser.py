from typing import Optional

from verbose_c.parser.ppg.parser import memoize, memoize_left_rec, logger, Parser
from ast import literal_eval

from verbose_c.parser.ppg.grammar import (
    Alt,
    Cut,
    Forced,
    Gather,
    Group,
    Item,
    Lookahead,
    LookaheadOrCut,
    MetaTuple,
    MetaList,
    NameLeaf,
    NamedItem,
    NamedItemList,
    NegativeLookahead,
    Opt,
    Plain,
    PositiveLookahead,
    Repeat0,
    Repeat1,
    Rhs,
    Rule,
    RuleList,
    RuleName,
    Grammar,
    StringLeaf,
)


# Keywords and soft keywords are listed at the end of the parser definition.
class GeneratedParser(Parser):
    @memoize
    def start(self) -> Optional[Grammar]:
        # start: grammar $
        mark = self._mark()
        if (grammar := self.grammar()) and (self.expect("ENDMARKER")):
            return grammar
        self._reset(mark)
        return None

    @memoize
    def grammar(self) -> Optional[Grammar]:
        # grammar: metas rules | rules
        mark = self._mark()
        if (metas := self.metas()) and (rules := self.rules()):
            return Grammar(rules, metas)
        self._reset(mark)
        if rules := self.rules():
            return Grammar(rules, [])
        self._reset(mark)
        return None

    @memoize
    def metas(self) -> Optional[MetaList]:
        # metas: meta metas | meta
        mark = self._mark()
        if (meta := self.meta()) and (metas := self.metas()):
            return [meta] + metas
        self._reset(mark)
        if meta := self.meta():
            return [meta]
        self._reset(mark)
        return None

    @memoize
    def meta(self) -> Optional[MetaTuple]:
        # meta: "@" NAME NEWLINE | "@" NAME NAME NEWLINE | "@" NAME STRING NEWLINE
        mark = self._mark()
        if (self.expect("@")) and (name := self.name()) and (self.expect("NEWLINE")):
            return (name.string, None)
        self._reset(mark)
        if (
            (self.expect("@"))
            and (a := self.name())
            and (b := self.name())
            and (self.expect("NEWLINE"))
        ):
            return (a.string, b.string)
        self._reset(mark)
        if (
            (self.expect("@"))
            and (name := self.name())
            and (string := self.string())
            and (self.expect("NEWLINE"))
        ):
            return (name.string, literal_eval(string.string))
        self._reset(mark)
        return None

    @memoize
    def rules(self) -> Optional[RuleList]:
        # rules: rule rules | rule
        mark = self._mark()
        if (rule := self.rule()) and (rules := self.rules()):
            return [rule] + rules
        self._reset(mark)
        if rule := self.rule():
            return [rule]
        self._reset(mark)
        return None

    @memoize
    def rule(self) -> Optional[Rule]:
        # rule: rulename memoflag? ":" alts NEWLINE INDENT more_alts DEDENT | rulename memoflag? ":" NEWLINE INDENT more_alts DEDENT | rulename memoflag? ":" alts NEWLINE
        mark = self._mark()
        if (
            (rulename := self.rulename())
            and (opt := self.memoflag(),)
            and (self.expect(":"))
            and (alts := self.alts())
            and (self.expect("NEWLINE"))
            and (self.expect("INDENT"))
            and (more_alts := self.more_alts())
            and (self.expect("DEDENT"))
        ):
            return Rule(rulename[0], rulename[1], Rhs(alts.alts + more_alts.alts), memo=opt)
        self._reset(mark)
        if (
            (rulename := self.rulename())
            and (opt := self.memoflag(),)
            and (self.expect(":"))
            and (self.expect("NEWLINE"))
            and (self.expect("INDENT"))
            and (more_alts := self.more_alts())
            and (self.expect("DEDENT"))
        ):
            return Rule(rulename[0], rulename[1], more_alts, memo=opt)
        self._reset(mark)
        if (
            (rulename := self.rulename())
            and (opt := self.memoflag(),)
            and (self.expect(":"))
            and (alts := self.alts())
            and (self.expect("NEWLINE"))
        ):
            return Rule(rulename[0], rulename[1], alts, memo=opt)
        self._reset(mark)
        return None

    @memoize
    def rulename(self) -> Optional[RuleName]:
        # rulename: NAME annotation | NAME
        mark = self._mark()
        if (name := self.name()) and (annotation := self.annotation()):
            return (name.string, annotation)
        self._reset(mark)
        if name := self.name():
            return (name.string, None)
        self._reset(mark)
        return None

    @memoize
    def memoflag(self) -> Optional[str]:
        # memoflag: '(' "memo" ')'
        mark = self._mark()
        if (self.expect("(")) and (self.expect("memo")) and (self.expect(")")):
            return "memo"
        self._reset(mark)
        return None

    @memoize
    def alts(self) -> Optional[Rhs]:
        # alts: alt "|" alts | alt
        mark = self._mark()
        if (alt := self.alt()) and (self.expect("|")) and (alts := self.alts()):
            return Rhs([alt] + alts.alts)
        self._reset(mark)
        if alt := self.alt():
            return Rhs([alt])
        self._reset(mark)
        return None

    @memoize
    def more_alts(self) -> Optional[Rhs]:
        # more_alts: "|" alts NEWLINE more_alts | "|" alts NEWLINE
        mark = self._mark()
        if (
            (self.expect("|"))
            and (alts := self.alts())
            and (self.expect("NEWLINE"))
            and (more_alts := self.more_alts())
        ):
            return Rhs(alts.alts + more_alts.alts)
        self._reset(mark)
        if (self.expect("|")) and (alts := self.alts()) and (self.expect("NEWLINE")):
            return Rhs(alts.alts)
        self._reset(mark)
        return None

    @memoize
    def alt(self) -> Optional[Alt]:
        # alt: items '$' action | items '$' | items action | items
        mark = self._mark()
        if (items := self.items()) and (self.expect("$")) and (action := self.action()):
            return Alt(items + [NamedItem(None, NameLeaf("ENDMARKER"))], action=action)
        self._reset(mark)
        if (items := self.items()) and (self.expect("$")):
            return Alt(items + [NamedItem(None, NameLeaf("ENDMARKER"))], action=None)
        self._reset(mark)
        if (items := self.items()) and (action := self.action()):
            return Alt(items, action=action)
        self._reset(mark)
        if items := self.items():
            return Alt(items, action=None)
        self._reset(mark)
        return None

    @memoize
    def items(self) -> Optional[NamedItemList]:
        # items: named_item items | named_item
        mark = self._mark()
        if (named_item := self.named_item()) and (items := self.items()):
            return [named_item] + items
        self._reset(mark)
        if named_item := self.named_item():
            return [named_item]
        self._reset(mark)
        return None

    @memoize
    def named_item(self) -> Optional[NamedItem]:
        # named_item: NAME annotation '=' ~ item | NAME '=' ~ item | item | forced_atom | lookahead
        mark = self._mark()
        cut = False
        if (
            (name := self.name())
            and (annotation := self.annotation())
            and (self.expect("="))
            and (cut := True)
            and (item := self.item())
        ):
            return NamedItem(name.string, item, annotation)
        self._reset(mark)
        if cut:
            return None
        cut = False
        if (
            (name := self.name())
            and (self.expect("="))
            and (cut := True)
            and (item := self.item())
        ):
            return NamedItem(name.string, item)
        self._reset(mark)
        if cut:
            return None
        if item := self.item():
            return NamedItem(None, item)
        self._reset(mark)
        if it := self.forced_atom():
            return NamedItem(None, it)
        self._reset(mark)
        if it := self.lookahead():
            return NamedItem(None, it)
        self._reset(mark)
        return None

    @memoize
    def forced_atom(self) -> Optional[LookaheadOrCut]:
        # forced_atom: '&' '&' ~ atom
        mark = self._mark()
        cut = False
        if (self.expect("&")) and (self.expect("&")) and (cut := True) and (atom := self.atom()):
            return Forced(atom)
        self._reset(mark)
        if cut:
            return None
        return None

    @memoize
    def lookahead(self) -> Optional[LookaheadOrCut]:
        # lookahead: '&' ~ atom | '!' ~ atom | '~'
        mark = self._mark()
        cut = False
        if (self.expect("&")) and (cut := True) and (atom := self.atom()):
            return PositiveLookahead(atom)
        self._reset(mark)
        if cut:
            return None
        cut = False
        if (self.expect("!")) and (cut := True) and (atom := self.atom()):
            return NegativeLookahead(atom)
        self._reset(mark)
        if cut:
            return None
        if self.expect("~"):
            return Cut()
        self._reset(mark)
        return None

    @memoize
    def item(self) -> Optional[Item]:
        # item: '[' ~ alts ']' | atom '?' | atom '*' | atom '+' | atom '.' atom '+' | atom
        mark = self._mark()
        cut = False
        if (self.expect("[")) and (cut := True) and (alts := self.alts()) and (self.expect("]")):
            return Opt(alts)
        self._reset(mark)
        if cut:
            return None
        if (atom := self.atom()) and (self.expect("?")):
            return Opt(atom)
        self._reset(mark)
        if (atom := self.atom()) and (self.expect("*")):
            return Repeat0(atom)
        self._reset(mark)
        if (atom := self.atom()) and (self.expect("+")):
            return Repeat1(atom)
        self._reset(mark)
        if (
            (sep := self.atom())
            and (self.expect("."))
            and (node := self.atom())
            and (self.expect("+"))
        ):
            return Gather(sep, node)
        self._reset(mark)
        if atom := self.atom():
            return atom
        self._reset(mark)
        return None

    @memoize
    def atom(self) -> Optional[Plain]:
        # atom: '(' ~ alts ')' | NAME | STRING
        mark = self._mark()
        cut = False
        if (self.expect("(")) and (cut := True) and (alts := self.alts()) and (self.expect(")")):
            return Group(alts)
        self._reset(mark)
        if cut:
            return None
        if name := self.name():
            return NameLeaf(name.string)
        self._reset(mark)
        if string := self.string():
            return StringLeaf(string.string)
        self._reset(mark)
        return None

    @memoize
    def action(self) -> Optional[str]:
        # action: "{" ~ target_atoms "}"
        mark = self._mark()
        cut = False
        if (
            (self.expect("{"))
            and (cut := True)
            and (target_atoms := self.target_atoms())
            and (self.expect("}"))
        ):
            return target_atoms
        self._reset(mark)
        if cut:
            return None
        return None

    @memoize
    def annotation(self) -> Optional[str]:
        # annotation: "[" ~ target_atoms "]"
        mark = self._mark()
        cut = False
        if (
            (self.expect("["))
            and (cut := True)
            and (target_atoms := self.target_atoms())
            and (self.expect("]"))
        ):
            return target_atoms
        self._reset(mark)
        if cut:
            return None
        return None

    @memoize
    def target_atoms(self) -> Optional[str]:
        # target_atoms: target_atom target_atoms | target_atom
        mark = self._mark()
        if (target_atom := self.target_atom()) and (target_atoms := self.target_atoms()):
            return target_atom + " " + target_atoms
        self._reset(mark)
        if target_atom := self.target_atom():
            return target_atom
        self._reset(mark)
        return None

    @memoize
    def target_atom(self) -> Optional[str]:
        # target_atom: "{" ~ target_atoms? "}" | "[" ~ target_atoms? "]" | NAME "*" | NAME | NUMBER | STRING | "?" | ":" | !"}" !"]" OP
        mark = self._mark()
        cut = False
        if (
            (self.expect("{"))
            and (cut := True)
            and (atoms := self.target_atoms(),)
            and (self.expect("}"))
        ):
            return "{" + (atoms or "") + "}"
        self._reset(mark)
        if cut:
            return None
        cut = False
        if (
            (self.expect("["))
            and (cut := True)
            and (atoms := self.target_atoms(),)
            and (self.expect("]"))
        ):
            return "[" + (atoms or "") + "]"
        self._reset(mark)
        if cut:
            return None
        if (name := self.name()) and (self.expect("*")):
            return name.string + "*"
        self._reset(mark)
        if name := self.name():
            return name.string
        self._reset(mark)
        if number := self.number():
            return number.string
        self._reset(mark)
        if string := self.string():
            return string.string
        self._reset(mark)
        if self.expect("?"):
            return "?"
        self._reset(mark)
        if self.expect(":"):
            return ":"
        self._reset(mark)
        if (
            (self.negative_lookahead(self.expect, "}"))
            and (self.negative_lookahead(self.expect, "]"))
            and (op := self.op())
        ):
            return op.string
        self._reset(mark)
        return None

    KEYWORDS = ()
    SOFT_KEYWORDS = ("memo",)
