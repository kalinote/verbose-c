import io
from pathlib import Path
from unittest.mock import patch

import pytest

from verbose_c.engine.engine import generate_parser, run_source_file
from verbose_c.fs.source_manager import SourceManager
from verbose_c.parser.lexer.enum import TokenType
from verbose_c.parser.lexer.tokenizer import Tokenizer
from verbose_c.parser.ppg.build import build_parser
from verbose_c.parser.ppg.python_generator import PythonParserGenerator


@pytest.mark.parametrize("newline, indentation", [("\n", "    "), ("\r\n", "\t")])
def test_grammar_layout_and_multiline_actions(tmp_path, newline, indentation):
    """验证多行语法、注释、缩进及文件末尾的组合行为。

    Args:
        tmp_path: 隔离的语法文件与源码目录。
        newline: 语法文件使用的换行符。
        indentation: 候选分支使用的缩进。
    """
    grammar_path = tmp_path / "layout.gram"
    grammar_source = (
        '# 语法文件注释\n'
        '@subheader """\nMARKER = "# //"\n"""\n'
        'start[list[str]]:\n'
        '    # 空白行和注释不应改变缩进\n\n'
        "    | &NAME !'bad' values=','.item+ END {\n"
        '        [value for value in values] # 动作中的注释\n'
        '      }\n'
        'item[str]:\n'
        '    | value=NAME { value.string }'
    )
    grammar_path.write_bytes(grammar_source.replace('    ', indentation).replace('\n', newline).encode('utf-8'))
    grammar, _, tokenizer = build_parser(str(grammar_path))
    output = io.StringIO()
    PythonParserGenerator(grammar, output).generate(str(grammar_path))
    namespace = {"__name__": "ppg_layout_test"}
    exec(output.getvalue(), namespace)
    source_path = tmp_path / "input.vbc"
    source_path.write_text("first, second", encoding="utf-8")
    parser = namespace["GeneratedParser"](Tokenizer(str(source_path), SourceManager()))

    assert parser.start() == ["first", "second"]
    assert namespace["MARKER"] == "# //"
    assert tokenizer.get_last_non_whitespace_token().string == "}"


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("int(n.string) // 2 ** 1", 3),
        ("0x_F + 0b10 + 0o7 + 1_000", 1024),
        (".5 + 1. + 1e1", 11.5),
        ("1_0.5e+1", 105.0),
        ("2j", 2j),
        ('r"\\n#//"', '\\n#//'),
        ('rb"\\x41"', b'\\x41'),
        ('"""第一行\n# // 第二行"""', '第一行\n# // 第二行'),
        ('f"值={n.string}"', '值=7'),
        ('((value := int(n.string)) > 0 and value)', 7),
        ('int(n.string) \\\n + 1', 8),
    ],
)
def test_python_actions_preserve_meaning(tmp_path, expression, expected):
    """验证共享词法器保留 Python 语义动作的实际执行结果。

    Args:
        tmp_path: 隔离的语法文件与源码目录。
        expression: 包含 Python 字面量或操作符的表达式。
        expected: 生成的解析器应返回的表达式结果。
    """
    grammar_path = tmp_path / "action.gram"
    grammar_path.write_text(
        'start: n=NUMBER END { {"value": ' + expression + '} }\n', encoding="utf-8",
    )
    grammar, _, _ = build_parser(str(grammar_path))
    output = io.StringIO()
    PythonParserGenerator(grammar, output).generate(str(grammar_path))
    namespace = {"__name__": "ppg_action_test"}
    exec(output.getvalue(), namespace)
    source_path = tmp_path / "input.vbc"
    source_path.write_text("7", encoding="utf-8")
    parser = namespace["GeneratedParser"](Tokenizer(str(source_path), SourceManager()))
    assert parser.start() == {"value": expected}


def test_forced_atom_and_end_marker_use_native_tokens(tmp_path):
    """验证连续前瞻符、截断符和结束标记可以生成并运行解析器。"""
    grammar_path = tmp_path / "forced.gram"
    grammar_path.write_text(
        "start: &&'ok' ~ values=','.NAME+ $ { [value.string for value in values] }\n",
        encoding="utf-8",
    )
    grammar, _, _ = build_parser(str(grammar_path))
    output = io.StringIO()
    PythonParserGenerator(grammar, output).generate(str(grammar_path))
    namespace = {"__name__": "ppg_forced_test"}
    exec(output.getvalue(), namespace)
    source_path = tmp_path / "input.vbc"
    source_path.write_text("ok first, second", encoding="utf-8")
    parser = namespace["GeneratedParser"](Tokenizer(str(source_path), SourceManager()))
    assert parser.start() == ["first", "second"]


def test_grammar_tokenizer_backtracking_keeps_furthest_diagnostic(tmp_path):
    """验证前瞻不消费 Token，回退后仍保留最远解析位置。"""
    grammar_path = tmp_path / "backtracking.gram"
    grammar_path.write_text("start: NAME END\n", encoding="utf-8")
    tokenizer = Tokenizer(str(grammar_path), SourceManager(), grammar_mode=True)
    mark = tokenizer.mark()
    first = tokenizer.peek()
    assert tokenizer.peek() is first
    assert tokenizer.getnext() is first
    assert tokenizer.getnext().string == ":"
    assert tokenizer.peek().string == "NAME"
    tokenizer.reset(mark)
    assert tokenizer.peek() is first
    assert tokenizer.diagnose().string == "NAME"
    assert isinstance(first.type, TokenType)


@pytest.mark.parametrize(
    "source, line",
    [
        ("start: NAME END\nbroken NAME\n", 2),
        ("start:\n    | NAME END\n  | NUMBER END\n", 3),
        ("start:\n\t| NAME END\n        | NUMBER END\n", 3),
        ("start: (NAME]\n", 1),
        ("start: (NAME\n", 1),
        ('start: "unterminated\n', 1),
        ("start: NAME { ` }\n", 1),
        ("start: NAME \\\n", 1),
    ],
)
def test_invalid_grammar_reports_source_location(tmp_path, source, line):
    """验证非法语法的诊断包含文件路径、正确行号和原始行内容。"""
    grammar_path = tmp_path / "invalid.gram"
    grammar_path.write_text(source, encoding="utf-8")
    with pytest.raises(SyntaxError) as error:
        build_parser(str(grammar_path))
    assert Path(error.value.filename) == grammar_path
    assert error.value.lineno == line
    assert error.value.offset > 0
    assert error.value.text.strip() == source.splitlines()[line - 1].strip()


def test_project_parser_generation_and_execution_without_python_tokenizer(tmp_path, monkeypatch):
    """验证项目语法通过共享词法器生成解析器并完成源码执行。

    Args:
        tmp_path: 隔离的解析器、源码和字节码输出目录。
        monkeypatch: 将编译入口指向本次实际生成的解析器。
    """
    grammar_path = Path(__file__).resolve().parents[1] / "Grammar" / "verbose_c.gram"
    output_path = tmp_path / "generated_parser.py"
    with patch("tokenize.generate_tokens", side_effect=AssertionError("PPG 不应调用 Python 分词器")):
        report = generate_parser(str(grammar_path), str(output_path))
    monkeypatch.setattr("verbose_c.engine.engine.default_parser_output", str(output_path))
    source_path = tmp_path / "program.vbc"
    source_path.write_text("int main() { return 2 + 3 * 4; }", encoding="utf-8")
    result = run_source_file(
        str(source_path), log_modules=set(), dump_modules=set(),
        output_path=str(tmp_path / "program.vbb"),
    )
    assert result.success, result.error
    assert result.exit_code == 14
    assert report.line_count > 0
    assert report.token_count > 0
