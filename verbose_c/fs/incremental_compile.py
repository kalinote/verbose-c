import hashlib
import json
import os
from typing import Any

from verbose_c.fs.artifact_store import ArtifactStore


class IncrementalCompiler:
    """依赖感知的入口翻译单元缓存复用。"""

    SCHEMA_VERSION = 1

    def __init__(self, artifact_store: ArtifactStore | None = None) -> None:
        self.artifact_store = artifact_store or ArtifactStore()
        self._dependency_edges: dict[str, set[str]] = {}

    def needs_recompile(
        self,
        entry_path: str,
        artifact_path: str | None = None,
        optimize_level: int = 0,
        refresh_parser: bool = False,
    ) -> bool:
        """判断入口文件及其依赖是否需要重新编译。"""
        if refresh_parser:
            return True

        entry_path = os.path.abspath(entry_path)
        artifact_path = self._artifact_path(entry_path, artifact_path)
        manifest = self._load_manifest(self.manifest_path_for_artifact(artifact_path))
        if manifest is None or not os.path.exists(artifact_path):
            return True

        if manifest.get("schema_version") != self.SCHEMA_VERSION:
            return True
        if manifest.get("entry_path") != entry_path:
            return True
        if manifest.get("artifact_path") != artifact_path:
            return True
        if manifest.get("format_version") != ArtifactStore.FORMAT_VERSION:
            return True
        if manifest.get("target_abi") != ArtifactStore.TARGET_ABI:
            return True
        if manifest.get("optimize_level") != optimize_level:
            return True
        if manifest.get("refresh_parser") != refresh_parser:
            return True

        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            return True

        for item in files:
            if not isinstance(item, dict):
                return True
            path = item.get("path")
            expected_hash = item.get("sha256")
            if not isinstance(path, str) or not isinstance(expected_hash, str):
                return True
            if not os.path.exists(path):
                return True
            try:
                if self.file_hash(path) != expected_hash:
                    return True
            except OSError:
                return True

        return False

    def write_manifest(
        self,
        entry_path: str,
        dependencies: list[str],
        artifact_path: str | None = None,
        optimize_level: int = 0,
        refresh_parser: bool = False,
    ) -> str:
        """写入入口文件对应的依赖侧车清单。"""
        entry_path = os.path.abspath(entry_path)
        artifact_path = self._artifact_path(entry_path, artifact_path)
        manifest_path = self.manifest_path_for_artifact(artifact_path)
        file_paths = [entry_path]
        file_paths.extend(os.path.abspath(path) for path in dependencies)
        unique_paths = sorted(dict.fromkeys(file_paths))

        manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "entry_path": entry_path,
            "artifact_path": artifact_path,
            "format_version": ArtifactStore.FORMAT_VERSION,
            "target_abi": ArtifactStore.TARGET_ABI,
            "optimize_level": optimize_level,
            "refresh_parser": refresh_parser,
            "files": [
                {"path": path, "sha256": self.file_hash(path)}
                for path in unique_paths
            ],
        }
        os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as file:
            json.dump(manifest, file, ensure_ascii=False, indent=2)
            file.write("\n")
        return manifest_path

    def record_dependency(self, from_path: str, included_path: str) -> None:
        """记录一条内存态 include 依赖边。"""
        from_path = os.path.abspath(from_path)
        included_path = os.path.abspath(included_path)
        self._dependency_edges.setdefault(from_path, set()).add(included_path)

    def get_transitive_dependencies(
        self,
        entry_path: str,
        artifact_path: str | None = None,
    ) -> list[str]:
        """从侧车清单读取入口文件的依赖列表。"""
        entry_path = os.path.abspath(entry_path)
        artifact_path = self._artifact_path(entry_path, artifact_path)
        manifest = self._load_manifest(self.manifest_path_for_artifact(artifact_path))
        if manifest is None:
            return []

        files = manifest.get("files")
        if not isinstance(files, list):
            return []

        dependencies = []
        for item in files:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if isinstance(path, str) and os.path.abspath(path) != entry_path:
                dependencies.append(path)
        return sorted(dict.fromkeys(dependencies))

    def invalidate(self, path: str) -> None:
        """使指定入口或依赖相关的缓存侧车清单失效。"""
        path = os.path.abspath(path)
        default_artifact_path = self.artifact_store.artifact_path_for_source(path)
        default_manifest_path = self.manifest_path_for_artifact(default_artifact_path)
        if os.path.exists(default_manifest_path):
            os.remove(default_manifest_path)

        for manifest_path in self._iter_manifest_candidates(path):
            manifest = self._load_manifest(manifest_path)
            if manifest is None:
                continue
            if self._manifest_references_path(manifest, path):
                try:
                    os.remove(manifest_path)
                except OSError:
                    pass

    def manifest_path_for_artifact(self, artifact_path: str) -> str:
        """返回 .vbb 产物对应的依赖侧车路径。"""
        return f"{os.path.abspath(artifact_path)}.deps.json"

    def file_hash(self, path: str) -> str:
        """计算文件内容的 SHA-256。"""
        hasher = hashlib.sha256()
        with open(os.path.abspath(path), "rb") as file:
            while True:
                chunk = file.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def _artifact_path(self, entry_path: str, artifact_path: str | None) -> str:
        if artifact_path:
            return os.path.abspath(artifact_path)
        return os.path.abspath(self.artifact_store.artifact_path_for_source(entry_path))

    def _load_manifest(self, manifest_path: str) -> dict[str, Any] | None:
        try:
            with open(manifest_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _iter_manifest_candidates(self, path: str):
        seen = set()
        search_roots = [os.getcwd(), os.path.dirname(path)]
        parent = os.path.dirname(path)
        grandparent = os.path.dirname(parent)
        if grandparent:
            search_roots.append(grandparent)

        for root in search_roots:
            if not root or not os.path.isdir(root):
                continue
            for current_root, _dirs, filenames in os.walk(root):
                for filename in filenames:
                    if not filename.endswith(".deps.json"):
                        continue
                    manifest_path = os.path.abspath(os.path.join(current_root, filename))
                    if manifest_path in seen:
                        continue
                    seen.add(manifest_path)
                    yield manifest_path

    def _manifest_references_path(self, manifest: dict[str, Any], path: str) -> bool:
        if manifest.get("entry_path") == path:
            return True
        files = manifest.get("files")
        if not isinstance(files, list):
            return False
        for item in files:
            if isinstance(item, dict) and item.get("path") == path:
                return True
        return False
