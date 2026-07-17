import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from verbose_c.error import VBCCompileError


class NativeExportKind(str, Enum):
    """native 产物类型。"""

    LISTING = "native-listing"
    RAW_BINARY = "native-bin"
    TEXT_SECTION = "native-text-bin"
    PE_IMAGE = "native-pe"
    MAP = "native-map"


_EXPORT_ORDER = (
    NativeExportKind.LISTING,
    NativeExportKind.RAW_BINARY,
    NativeExportKind.TEXT_SECTION,
    NativeExportKind.PE_IMAGE,
    NativeExportKind.MAP,
)
_EXPORT_SUFFIXES = {
    NativeExportKind.LISTING: ".native.md",
    NativeExportKind.RAW_BINARY: ".native.bin",
    NativeExportKind.TEXT_SECTION: ".text.bin",
    NativeExportKind.PE_IMAGE: ".exe",
    NativeExportKind.MAP: ".native.map.json",
}
_EXPORT_MEDIA_TYPES = {
    NativeExportKind.LISTING: "text/markdown",
    NativeExportKind.RAW_BINARY: "application/vnd.verbose-c.native-code",
    NativeExportKind.TEXT_SECTION: "application/vnd.microsoft.portable-executable.text",
    NativeExportKind.PE_IMAGE: "application/vnd.microsoft.portable-executable",
    NativeExportKind.MAP: "application/json",
}
_EXPORT_ALIASES = {
    "asm": NativeExportKind.LISTING,
    **{kind.value: kind for kind in _EXPORT_ORDER},
}


def parse_native_export_kinds(specifications: list[str]) -> frozenset[NativeExportKind]:
    """解析逗号分隔或重复提供的 native 导出类型。"""
    kinds: set[NativeExportKind] = set()
    for specification in specifications:
        for item in specification.split(","):
            name = item.strip().lower()
            if not name:
                continue
            if name == "native-bundle":
                kinds.update(_EXPORT_ORDER)
                continue
            kind = _EXPORT_ALIASES.get(name)
            if kind is None:
                supported = ", ".join(kind.value for kind in _EXPORT_ORDER)
                raise ValueError(f"--emit 存在不支持的类型: {name}；支持 {supported}, native-bundle")
            kinds.add(kind)
    if not kinds:
        raise ValueError("--emit 至少需要一个导出类型")
    return frozenset(kinds)


@dataclass(frozen=True)
class NativeExportRequest:
    """一次 native 产物导出请求。"""

    outputs: dict[NativeExportKind, str] = field(default_factory=dict)
    manifest_path: str | None = None

    @property
    def enabled(self) -> bool:
        """判断请求是否包含实际产物。"""
        return bool(self.outputs)

    @classmethod
    def organized(
        cls,
        source_filename: str,
        output_dir: str,
        kinds: frozenset[NativeExportKind],
    ) -> "NativeExportRequest":
        """按统一目录和基础文件名创建导出请求。"""
        if not output_dir:
            raise ValueError("--emit-dir 不能为空")
        source_name = os.path.splitext(os.path.basename(source_filename))[0]
        base_name = re.sub(r"[^A-Za-z0-9._-]", "_", source_name) or "native"
        outputs = {
            kind: os.path.join(output_dir, base_name + _EXPORT_SUFFIXES[kind])
            for kind in _EXPORT_ORDER
            if kind in kinds
        }
        return cls(
            outputs=outputs,
            manifest_path=os.path.join(output_dir, base_name + ".native.manifest.json"),
        )

@dataclass(frozen=True)
class ExportedArtifact:
    """单个已写出的 native 产物摘要。"""

    kind: NativeExportKind
    path: str
    media_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class NativeExportReport:
    """一次 native 导出的结构化结果。"""

    source_filename: str
    target: str
    entry: str
    artifacts: tuple[ExportedArtifact, ...]
    manifest_path: str | None = None


class NativeArtifactExporter:
    """统一构建、写出并校验 native 产物。"""

    def __init__(self, open_file: Callable[..., Any] = open):
        self._open = open_file

    def export(self, program: Any, request: NativeExportRequest, source_filename: str) -> NativeExportReport:
        """生成请求中的全部产物，完成写后校验并返回结构化报告。"""
        if not request.enabled:
            return NativeExportReport(source_filename, program.target.value, program.entry.name, ())

        from verbose_c.compiler.native import (
            NativeCodegenError,
            build_native_pe_image,
            format_native_code_program,
            native_code_program_map,
            validate_native_code_map_bytes,
            validate_native_code_program_map,
            validate_native_pe_image_bytes,
            validate_native_text_section_map_bytes,
        )

        kinds = set(request.outputs)
        metadata = None
        if kinds & {NativeExportKind.TEXT_SECTION, NativeExportKind.PE_IMAGE, NativeExportKind.MAP}:
            metadata = native_code_program_map(program)
        if NativeExportKind.MAP in kinds:
            try:
                validate_native_code_program_map(program, metadata)
            except NativeCodegenError as error:
                raise VBCCompileError(
                    f"导出 x64 机器码 map 自检失败: {error}",
                    filepath=source_filename,
                ) from error

        binary_payloads: dict[NativeExportKind, bytes] = {}
        text_payloads: dict[NativeExportKind, str] = {}
        if NativeExportKind.LISTING in kinds:
            text_payloads[NativeExportKind.LISTING] = format_native_code_program(program)
        if NativeExportKind.RAW_BINARY in kinds:
            binary_payloads[NativeExportKind.RAW_BINARY] = program.code
        if NativeExportKind.TEXT_SECTION in kinds:
            raw_padding_size = metadata["sections"][0]["raw_padding_size"]
            binary_payloads[NativeExportKind.TEXT_SECTION] = program.code + bytes(raw_padding_size)
        if NativeExportKind.PE_IMAGE in kinds:
            try:
                binary_payloads[NativeExportKind.PE_IMAGE] = build_native_pe_image(program.code, metadata)
            except NativeCodegenError as error:
                raise VBCCompileError(
                    f"导出最小 PE image 生成失败: {error}",
                    filepath=source_filename,
                ) from error
        if NativeExportKind.MAP in kinds:
            text_payloads[NativeExportKind.MAP] = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"

        written_bytes: dict[NativeExportKind, bytes] = {}
        for kind in _EXPORT_ORDER:
            path = request.outputs.get(kind)
            if path is None:
                continue
            if kind in binary_payloads:
                written_bytes[kind] = self._write_bytes(path, binary_payloads[kind], source_filename, kind)
            else:
                written_bytes[kind] = self._write_text(path, text_payloads[kind], source_filename, kind)

        if NativeExportKind.TEXT_SECTION in written_bytes:
            try:
                validate_native_text_section_map_bytes(written_bytes[NativeExportKind.TEXT_SECTION], metadata)
            except NativeCodegenError as error:
                raise VBCCompileError(
                    f"导出 PE .text raw section 与 map 自检失败: {error}",
                    filepath=source_filename,
                ) from error
        if NativeExportKind.PE_IMAGE in written_bytes:
            try:
                validate_native_pe_image_bytes(written_bytes[NativeExportKind.PE_IMAGE], metadata)
            except NativeCodegenError as error:
                raise VBCCompileError(
                    f"导出最小 PE image 自检失败: {error}",
                    filepath=source_filename,
                ) from error
        if NativeExportKind.MAP in written_bytes:
            if NativeExportKind.RAW_BINARY in written_bytes:
                try:
                    validate_native_code_map_bytes(written_bytes[NativeExportKind.RAW_BINARY], metadata)
                except NativeCodegenError as error:
                    raise VBCCompileError(
                        f"导出 x64 原始机器码与 map 自检失败: {error}",
                        filepath=source_filename,
                    ) from error
            if NativeExportKind.TEXT_SECTION in written_bytes:
                try:
                    validate_native_text_section_map_bytes(written_bytes[NativeExportKind.TEXT_SECTION], metadata)
                except NativeCodegenError as error:
                    raise VBCCompileError(
                        f"导出 PE .text raw section 与 map 自检失败: {error}",
                        filepath=source_filename,
                    ) from error
            if NativeExportKind.PE_IMAGE in written_bytes:
                try:
                    validate_native_pe_image_bytes(written_bytes[NativeExportKind.PE_IMAGE], metadata)
                except NativeCodegenError as error:
                    raise VBCCompileError(
                        f"导出最小 PE image 与 map 自检失败: {error}",
                        filepath=source_filename,
                    ) from error

        artifacts = tuple(
            ExportedArtifact(
                kind=kind,
                path=request.outputs[kind],
                media_type=_EXPORT_MEDIA_TYPES[kind],
                size=len(written_bytes[kind]),
                sha256=hashlib.sha256(written_bytes[kind]).hexdigest(),
            )
            for kind in _EXPORT_ORDER
            if kind in written_bytes
        )
        report = NativeExportReport(
            source_filename=source_filename,
            target=program.target.value,
            entry=program.entry.name,
            artifacts=artifacts,
            manifest_path=request.manifest_path,
        )
        if request.manifest_path is not None:
            self._write_manifest(report)
        return report

    def _write_bytes(
        self,
        path: str,
        content: bytes,
        source_filename: str,
        kind: NativeExportKind,
    ) -> bytes:
        """写出二进制产物并读回检查。"""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._open(path, "wb") as output_file:
            output_file.write(content)
        with self._open(path, "rb") as output_file:
            written = output_file.read()
        if written != content:
            messages = {
                NativeExportKind.RAW_BINARY: "导出 x64 原始机器码自检失败: 写入内容与 NativeCodeProgram.code 不一致",
                NativeExportKind.TEXT_SECTION: "导出 PE .text raw section 自检失败: 写入内容与补零后的机器码不一致",
                NativeExportKind.PE_IMAGE: "导出最小 PE image 自检失败: 写入内容与生成结果不一致",
            }
            raise VBCCompileError(messages[kind], filepath=source_filename)
        return written

    def _write_text(
        self,
        path: str,
        content: str,
        source_filename: str,
        kind: NativeExportKind,
    ) -> bytes:
        """写出 UTF-8 文本产物并读回检查。"""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._open(path, "w", encoding="utf-8") as output_file:
            output_file.write(content)
        with self._open(path, "r", encoding="utf-8") as output_file:
            written = output_file.read()
        if written != content:
            label = "x64 伪汇编" if kind == NativeExportKind.LISTING else "x64 机器码 map"
            raise VBCCompileError(f"导出 {label} 自检失败: 写入内容与生成结果不一致", filepath=source_filename)
        with self._open(path, "rb") as output_file:
            return output_file.read()

    def _write_manifest(self, report: NativeExportReport) -> None:
        """写出统一 native 产物 manifest 并校验 JSON。"""
        manifest_dir = os.path.dirname(os.path.abspath(report.manifest_path))
        os.makedirs(manifest_dir, exist_ok=True)
        metadata = {
            "schema_version": 1,
            "source": report.source_filename,
            "target": report.target,
            "entry": report.entry,
            "artifacts": [
                {
                    "kind": artifact.kind.value,
                    "path": os.path.relpath(os.path.abspath(artifact.path), manifest_dir),
                    "media_type": artifact.media_type,
                    "size": artifact.size,
                    "sha256": artifact.sha256,
                }
                for artifact in report.artifacts
            ],
        }
        content = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        with self._open(report.manifest_path, "w", encoding="utf-8") as manifest_file:
            manifest_file.write(content)
        with self._open(report.manifest_path, "r", encoding="utf-8") as manifest_file:
            try:
                written = json.load(manifest_file)
            except json.JSONDecodeError as error:
                raise VBCCompileError(
                    f"导出 native manifest 自检失败: JSON 解析失败: {error}",
                    filepath=report.source_filename,
                ) from error
        if written != metadata:
            raise VBCCompileError(
                "导出 native manifest 自检失败: 写入内容与导出报告不一致",
                filepath=report.source_filename,
            )
