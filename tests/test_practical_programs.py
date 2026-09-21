import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from verbose_c.compiler.native.runner import can_run_native_memory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = PROJECT_ROOT / "tests" / "grammar"
CALCULATOR_MENU = "整数计算器：1加 2减 3乘 4除 5取余\n运算编号："
CALCULATOR_INPUT = CALCULATOR_MENU + "两个整数："
GCD_OUTPUT = "\n最大公约数(48,18)：6\n最大公约数(1071,462)：21\n"


@pytest.fixture(scope="module", params=[0, 1], ids=["O0", "O1"])
def compiled_programs(request, tmp_path_factory):
    """通过真实 CLI 编译样例，保留字节码、exe 和运行记录。

    每个优化等级使用独立目录；复制源码和 include 文件，避免写入样例目录。
    所有样例同时生成字节码和独立 exe。
    """
    root = tmp_path_factory.mktemp(f"practical-O{request.param}")
    sources = root / "sources"
    artifacts = root / "artifacts"
    sources.mkdir()
    artifacts.mkdir()
    (root / "runs").mkdir()
    shutil.copy2(PROJECT_ROOT / "tests" / "practical_console.inc", root / "practical_console.inc")
    for source in PROGRAMS.glob("practical_*.vbc"):
        shutil.copy2(source, sources / source.name)
    for source in sorted(sources.glob("*.vbc")):
        name = source.stem.removeprefix("practical_")
        command = [sys.executable, "-m", "verbose_c.cli", str(source), f"-O{request.param}",
                   "-o", str(artifacts / f"{name}.vbb")]
        command += ["--emit-exe", str(artifacts / f"{name}.exe")]
        compiled = subprocess.run(command, input=b"", capture_output=True, timeout=30,
                                  cwd=PROJECT_ROOT, env={**os.environ, "PYTHONUTF8": "1"})
        assert compiled.returncode == 0, (source.name, compiled.stdout.decode("utf-8"), compiled.stderr.decode("utf-8"))
        assert "警告" not in compiled.stdout.decode("utf-8"), (source.name, compiled.stdout.decode("utf-8"))
        assert compiled.stderr == b""
    return root, request.param


@pytest.mark.parametrize("filename,data,expected,error,status", [
    pytest.param("array_sort", "", "排序结果：1 2 3 5 9\n合计：20\n", "", 0, id="array_sort"),
    pytest.param("calculator", "1 17 25\n", CALCULATOR_INPUT + "结果：42\n", "", 0, id="calculator_add"),
    pytest.param("calculator", "2 17 25\n", CALCULATOR_INPUT + "结果：-8\n", "", 0, id="calculator_subtract"),
    pytest.param("calculator", "3 -2147483648 -1\n", CALCULATOR_INPUT + "结果：2147483648\n", "", 0, id="calculator_wide_result"),
    pytest.param("calculator", "4 -7 3\n", CALCULATOR_INPUT + "结果：-2\n", "", 0, id="calculator_divide"),
    pytest.param("calculator", "5 -7 3\n", CALCULATOR_INPUT + "结果：-1\n", "", 0, id="calculator_remainder"),
    pytest.param("calculator", "9\n", CALCULATOR_MENU, "运算编号必须为 1～5。", 2, id="calculator_bad_operation"),
    pytest.param("calculator", "4 3 0\n", CALCULATOR_INPUT, "除数不能为零。", 2, id="calculator_zero_guard"),
    pytest.param("calculator", "", CALCULATOR_MENU, "输入错误：缺少整数。", 2, id="calculator_eof"),
    pytest.param("calculator", "1 12x 1\n", CALCULATOR_INPUT, "输入错误：需要十进制整数。", 2, id="calculator_bad_number"),
    pytest.param("calculator", "1 2147483648 0\n", CALCULATOR_INPUT, "输入错误：整数超出 32 位范围。", 2, id="calculator_input_overflow"),
    pytest.param("prime_report", "30\n", "素数统计，上限(1～5000)：素数：2 3 5 7 11 13 17 19 23 29\n数量：10\n总和：129\n", "", 0, id="primes_30"),
    pytest.param("prime_report", "1\n", "素数统计，上限(1～5000)：素数：\n数量：0\n总和：0\n", "", 0, id="primes_empty"),
    pytest.param("prime_report", "5001\n", "素数统计，上限(1～5000)：", "上限必须在 1～5000 之间。", 2, id="primes_bad_limit"),
    pytest.param("recursive_math", "0\n", "阶乘参数(0～20)：阶乘：1" + GCD_OUTPUT, "", 0, id="factorial_zero"),
    pytest.param("recursive_math", "20\n", "阶乘参数(0～20)：阶乘：2432902008176640000" + GCD_OUTPUT, "", 0, id="factorial_20"),
    pytest.param("recursive_math", "21\n", "阶乘参数(0～20)：", "阶乘参数必须在 0～20 之间。", 2, id="factorial_bad_limit"),
    pytest.param("sales_receipt", "", "订单小票（元）\n图书：74.82\n杯子：35.00\n文具：19.62\n订单数：3\n总额：129.44\n", "", 0, id="sales_receipt"),
    pytest.param("temperature_table", "", "摄氏℃ | 华氏℉ | 开尔文K\n-20 | -4 | 253.15\n0 | 32 | 273.15\n20 | 68 | 293.15\n40 | 104 | 313.15\n", "", 0, id="temperature_table"),
    pytest.param("runtime_divide_by_zero", "5\n", "请输入除数：商：20\n", "", 0, id="runtime_divide_ok"),
    pytest.param("runtime_divide_by_zero", "0\n", "请输入除数：", "除零错误", 1, id="runtime_divide_zero"),
    pytest.param("vm_inventory", "", "库存件数：28\n库存价值（元）：146.47\n", "", 0, id="vm_inventory"),
])
def test_practical_program_execution(compiled_programs, request, filename, data, expected, error, status):
    """实际执行源码、字节码和独立 exe，逐字节核对输出、诊断及退出码。"""
    root, level = compiled_programs
    commands = {
        "VM": [sys.executable, "-m", "verbose_c.cli", str(root / "sources" / f"practical_{filename}.vbc"), f"-O{level}"],
        "字节码": [sys.executable, "-m", "verbose_c.cli", str(root / "artifacts" / f"{filename}.vbb")],
    }
    if can_run_native_memory():
        standalone = root / "standalone" / filename
        standalone.mkdir(parents=True, exist_ok=True)
        executable = standalone / f"{filename}.exe"
        shutil.copy2(root / "artifacts" / executable.name, executable)
        commands["EXE"] = [str(executable)]
        if filename == "vm_inventory":
            commands["Native 内存"] = [
                sys.executable, "-c",
                "import sys\nfrom verbose_c.engine.engine import run_source_file\n"
                "result = run_source_file(sys.argv[1], optimize_level=int(sys.argv[2]), "
                "run_native_memory=True, log_modules=set(), dump_modules=set())\nsys.exit(result.exit_code)",
                str(root / "sources" / f"practical_{filename}.vbc"), str(level),
            ]
    records = []
    for backend, command in commands.items():
        completed = subprocess.run(command, input=data.encode("utf-8"), capture_output=True, timeout=20,
                                   cwd=PROJECT_ROOT if backend != "EXE" else standalone,
                                   env={**os.environ, "PYTHONUTF8": "1"})
        output = completed.stdout.decode("utf-8")
        diagnostic = completed.stderr.decode("utf-8")
        records.append({"后端": backend, "命令": command, "退出码": completed.returncode,
                        "标准输出": output, "标准错误": diagnostic})
        (root / "runs" / f"{request.node.callspec.id}.json").write_text(
            json.dumps({"样例": filename, "优化等级": level, "输入": data, "执行记录": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert completed.returncode == status, (backend, output, diagnostic)
        assert output.encode("utf-8") == expected.encode("utf-8"), (backend, output)
        if error:
            assert error in diagnostic, (backend, diagnostic)
        else:
            assert completed.stderr == b"", (backend, diagnostic)


def test_inventory_native_executable_exists(compiled_programs):
    """库存示例与其他正式样例一样生成可独立分发的 exe。"""
    root, level = compiled_programs
    executable = root / "artifacts" / "vm_inventory.exe"
    assert executable.read_bytes().startswith(b"MZ")
