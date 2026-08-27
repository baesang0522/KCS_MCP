from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".ipynb_checkpoints",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
}


class WorkspaceTools:
    """
    현재 JupyterLab 작업공간 내부의 파일 시스템을 탐색하기 위한 툴 모음입니다.

    모든 경로는 workspace_root를 기준으로 한 상대 경로로 처리됩니다.
    Agent가 작업공간 바깥의 파일에 접근하지 못하도록 경로 검증을 수행합니다.

    workspace_root는 Agent나 LLM이 직접 지정하는 값이 아니라,
    JupyterLab 세션 또는 Tool Server에서 결정하여 주입하는 것을 권장합니다.
    """

    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root).resolve()

        if not self.root.exists():
            raise FileNotFoundError(
                f"작업공간 루트가 존재하지 않습니다: {workspace_root}"
            )

        if not self.root.is_dir():
            raise NotADirectoryError(
                f"작업공간 루트가 디렉토리가 아닙니다: {workspace_root}"
            )

    def _resolve_path(self, path: str) -> Path:
        """
        Agent가 전달한 상대 경로를 안전한 실제 경로로 변환합니다.

        `..` 또는 심볼릭 링크 등을 이용해 작업공간 바깥으로 접근하려는 경우
        PermissionError를 발생시킵니다.

        Args:
            path:
                작업공간 기준 상대 경로입니다.

                예:
                    "."
                    "src"
                    "src/services"
                    "notebooks/test.ipynb"

        Returns:
            작업공간 내부에 존재하는 절대 Path 객체를 반환합니다.

        Raises:
            PermissionError:
                변환된 경로가 작업공간 외부를 가리키는 경우 발생합니다.

            FileNotFoundError:
                지정한 경로가 존재하지 않는 경우 발생합니다.
        """
        target = (self.root / path).resolve()

        # 작업공간 루트 자체이거나, 반드시 루트 하위 경로여야 합니다.
        if target != self.root and self.root not in target.parents:
            raise PermissionError(
                f"작업공간 외부 경로에는 접근할 수 없습니다: {path}"
            )

        if not target.exists():
            raise FileNotFoundError(
                f"경로가 존재하지 않습니다: {path}"
            )

        return target

    def _relative_path(self, path: Path) -> str:
        """
        절대 경로를 Agent에게 노출할 작업공간 기준 상대 경로로 변환합니다.
        """
        if path == self.root:
            return "."

        return path.relative_to(self.root).as_posix()

    def _should_ignore(
        self,
        path: Path,
        include_hidden: bool,
    ) -> bool:
        """
        프로젝트 탐색 결과에서 제외할 파일 또는 디렉토리인지 판단합니다.

        숨김 파일을 제외하도록 설정한 경우 이름이 "."으로 시작하는 항목은
        기본적으로 반환하지 않습니다.

        또한 .git, .venv, node_modules처럼 코드 탐색에 대부분 불필요하면서
        항목 수가 매우 많은 디렉토리는 기본적으로 제외합니다.
        """
        name = path.name

        if not include_hidden and name.startswith("."):
            return True

        if path.is_dir() and name in DEFAULT_IGNORE_DIRS:
            return True

        return False

    def list_files(
        self,
        path: str = ".",
        include_hidden: bool = False,
        max_entries: int = 200,
    ) -> dict[str, Any]:
        """
        지정한 디렉토리 바로 아래의 파일과 디렉토리 목록을 조회합니다.

        이 툴은 특정 디렉토리 내부를 국소적으로 탐색할 때 사용합니다.
        하위 디렉토리를 재귀적으로 탐색하지 않습니다.

        프로젝트 전체 구조를 처음 파악해야 하는 경우에는
        `get_project_tree`를 사용하는 것이 더 적합합니다.

        권장 사용 상황:
        - 현재 디렉토리에 어떤 파일이 존재하는지 확인할 때
        - 특정 패키지 또는 모듈 디렉토리 내부를 살펴볼 때
        - 파일 내용을 읽기 전에 관련 파일을 찾을 때
        - 프로젝트 전체를 읽지 않고 필요한 영역만 단계적으로 탐색할 때

        권장 Agent 사용 흐름:
        1. 프로젝트 구조가 전혀 알려지지 않았다면 `get_project_tree`를 사용합니다.
        2. 관련 디렉토리를 발견했다면 이 툴로 해당 디렉토리를 자세히 확인합니다.
        3. 관련 파일을 찾은 뒤 `read_file` 또는 `search_code`를 사용합니다.

        Args:
            path:
                조회할 디렉토리의 작업공간 기준 상대 경로입니다.

                예:
                    "."
                    "src"
                    "src/services"
                    "tests"

                절대 경로를 직접 전달하지 않는 것을 권장합니다.

            include_hidden:
                이름이 "."으로 시작하는 숨김 파일 및 디렉토리를
                결과에 포함할지 여부입니다.

                기본값은 False입니다.

                단, .git, .venv, node_modules 등 코드 탐색에 불필요한
                일부 디렉토리는 별도 정책에 따라 제외될 수 있습니다.

            max_entries:
                최대 반환 항목 수입니다.

                대규모 디렉토리의 파일 목록이 모델의 컨텍스트를
                과도하게 차지하는 것을 방지하기 위한 제한입니다.

                실제 항목 수가 이 값을 초과하면 결과의
                `truncated`가 True가 됩니다.

        Returns:
            다음 형식의 dictionary를 반환합니다.

            {
                "path": "src",
                "entries": [
                    {
                        "name": "services",
                        "path": "src/services",
                        "type": "directory"
                    },
                    {
                        "name": "main.py",
                        "path": "src/main.py",
                        "type": "file",
                        "size": 4210
                    }
                ],
                "truncated": False
            }

            `path` 값은 모두 작업공간 기준 상대 경로입니다.

            파일의 `size`는 byte 단위입니다.
            디렉토리에는 size 값을 반환하지 않습니다.

        Raises:
            FileNotFoundError:
                지정한 경로가 존재하지 않는 경우 발생합니다.

            NotADirectoryError:
                지정한 경로가 디렉토리가 아닌 경우 발생합니다.

            PermissionError:
                작업공간 바깥의 경로에 접근하려는 경우 발생합니다.

            ValueError:
                max_entries가 1보다 작은 경우 발생합니다.

        Agent 주의사항:
            - 이 툴은 파일 내용을 읽지 않습니다.
            - 파일명만 보고 실제 코드 동작을 추측하지 마세요.
            - 관련 파일을 발견했다면 반드시 `read_file`이나
              `search_code`로 실제 내용을 확인하세요.
            - 같은 디렉토리를 불필요하게 반복 조회하지 마세요.
        """
        if max_entries < 1:
            raise ValueError("max_entries는 1 이상이어야 합니다.")

        target = self._resolve_path(path)

        if not target.is_dir():
            raise NotADirectoryError(
                f"디렉토리가 아닙니다: {path}"
            )

        entries: list[dict[str, Any]] = []
        truncated = False

        try:
            children = sorted(
                target.iterdir(),
                key=lambda p: (
                    not p.is_dir(),
                    p.name.lower(),
                ),
            )
        except PermissionError as exc:
            raise PermissionError(
                f"디렉토리를 읽을 권한이 없습니다: {path}"
            ) from exc

        for child in children:
            if self._should_ignore(
                child,
                include_hidden=include_hidden,
            ):
                continue

            if len(entries) >= max_entries:
                truncated = True
                break

            entry: dict[str, Any] = {
                "name": child.name,
                "path": self._relative_path(child),
                "type": (
                    "directory"
                    if child.is_dir()
                    else "file"
                ),
            }

            if child.is_file():
                try:
                    entry["size"] = child.stat().st_size
                except OSError:
                    entry["size"] = None

            entries.append(entry)

        return {
            "path": self._relative_path(target),
            "entries": entries,
            "truncated": truncated,
        }

    def get_project_tree(
        self,
        path: str = ".",
        max_depth: int = 4,
        include_hidden: bool = False,
        max_entries: int = 500,
    ) -> dict[str, Any]:
        """
        프로젝트의 디렉토리 구조를 재귀적으로 조회합니다.

        이 툴은 Agent가 처음 보는 프로젝트의 전체적인 구조를 파악하거나,
        코드 수정 계획을 세우기 전에 관련 모듈의 위치를 찾을 때 사용합니다.

        `list_files`가 특정 디렉토리 바로 아래만 조회하는 국소 탐색 툴이라면,
        이 툴은 여러 단계의 하위 디렉토리를 한 번에 확인하기 위한
        프로젝트 구조 탐색 툴입니다.

        권장 사용 상황:
        - 처음 보는 프로젝트의 전체 구조를 파악할 때
        - 소스 코드, 테스트 코드, 설정 파일의 위치를 찾을 때
        - 어떤 패키지와 모듈들이 존재하는지 확인할 때
        - Planner가 코드 수정 계획을 세우기 전에 관련 영역을 찾을 때
        - main.py, app.py, pyproject.toml, package.json 등의
          주요 진입점 또는 설정 파일 위치를 확인할 때

        권장 Agent 사용 흐름:
        1. 처음 보는 프로젝트라면 이 툴로 프로젝트 구조를 파악합니다.
        2. 사용자 요청과 관련 있어 보이는 디렉토리를 찾습니다.
        3. 해당 디렉토리는 `list_files`를 이용해 더 자세히 탐색합니다.
        4. 실제 구현 위치는 `search_code` 또는 `read_file`로 확인합니다.
        5. 파일이나 디렉토리 이름만 보고 구현을 단정하지 않습니다.

        Args:
            path:
                프로젝트 트리를 조회할 시작 디렉토리입니다.

                작업공간 기준 상대 경로를 사용합니다.

                일반적으로 전체 프로젝트를 확인할 때는 "."을 사용합니다.

            max_depth:
                몇 단계의 하위 디렉토리까지 재귀적으로 탐색할지 지정합니다.

                예:
                    1:
                        현재 디렉토리 바로 아래까지만 확인

                    2:
                        현재 디렉토리와 그 하위 디렉토리까지 확인

                    4:
                        일반적인 프로젝트 구조 파악에 적합한 기본값

                너무 큰 값을 사용하면 결과가 커져 모델 컨텍스트를
                불필요하게 사용할 수 있습니다.

            include_hidden:
                이름이 "."으로 시작하는 숨김 파일과 디렉토리를
                포함할지 여부입니다.

                기본값은 False입니다.

            max_entries:
                전체 프로젝트 트리에 포함할 최대 파일 및 디렉토리 개수입니다.

                탐색 과정에서 이 값을 초과하면 탐색을 중단하고
                `truncated`를 True로 반환합니다.

        Returns:
            프로젝트 구조를 중첩된 dictionary 형태로 반환합니다.

            예:

            {
                "path": ".",
                "tree": {
                    "name": ".",
                    "path": ".",
                    "type": "directory",
                    "children": [
                        {
                            "name": "src",
                            "path": "src",
                            "type": "directory",
                            "children": [
                                {
                                    "name": "main.py",
                                    "path": "src/main.py",
                                    "type": "file",
                                    "size": 4210
                                }
                            ]
                        }
                    ]
                },
                "total_entries": 12,
                "truncated": False
            }

            `total_entries`는 root 노드를 제외하고 반환 결과에 포함된
            파일 및 디렉토리의 총 개수입니다.

        Raises:
            FileNotFoundError:
                지정한 경로가 존재하지 않는 경우 발생합니다.

            NotADirectoryError:
                지정한 경로가 디렉토리가 아닌 경우 발생합니다.

            PermissionError:
                작업공간 바깥으로 접근하려는 경우 발생합니다.

            ValueError:
                max_depth 또는 max_entries가 1보다 작은 경우 발생합니다.

        Agent 주의사항:
            - 이 툴의 목적은 프로젝트 구조 파악입니다.
            - 소스 코드 내용을 확인하는 용도로 사용하지 마세요.
            - 파일명이나 디렉토리명만으로 코드 동작을 추측하지 마세요.
            - 관련 파일을 찾았다면 `search_code`나 `read_file`로
              실제 구현을 반드시 확인하세요.
            - `truncated`가 True인 경우 max_depth나 max_entries를
              무작정 크게 늘리기보다 관련 디렉토리를 좁혀서
              `list_files`로 탐색하는 것을 우선합니다.
        """
        if max_depth < 1:
            raise ValueError(
                "max_depth는 1 이상이어야 합니다."
            )

        if max_entries < 1:
            raise ValueError(
                "max_entries는 1 이상이어야 합니다."
            )

        target = self._resolve_path(path)

        if not target.is_dir():
            raise NotADirectoryError(
                f"디렉토리가 아닙니다: {path}"
            )

        total_entries = 0
        truncated = False

        def build_tree(
            current: Path,
            current_depth: int,
        ) -> dict[str, Any]:
            nonlocal total_entries, truncated

            node: dict[str, Any] = {
                "name": (
                    "."
                    if current == self.root
                    else current.name
                ),
                "path": self._relative_path(current),
                "type": "directory",
                "children": [],
            }

            # 현재 디렉토리가 최대 깊이에 도달했다면
            # 그 아래는 더 이상 탐색하지 않습니다.
            if current_depth >= max_depth:
                return node

            try:
                children = sorted(
                    current.iterdir(),
                    key=lambda p: (
                        not p.is_dir(),
                        p.name.lower(),
                    ),
                )
            except PermissionError:
                # 전체 호출을 실패시키기보다
                # 해당 디렉토리만 접근 불가 상태로 표시합니다.
                node["access_error"] = True
                return node

            for child in children:
                if self._should_ignore(
                    child,
                    include_hidden=include_hidden,
                ):
                    continue

                if total_entries >= max_entries:
                    truncated = True
                    break

                total_entries += 1

                if child.is_dir():
                    child_node = build_tree(
                        child,
                        current_depth + 1,
                    )

                else:
                    child_node: dict[str, Any] = {
                        "name": child.name,
                        "path": self._relative_path(child),
                        "type": "file",
                    }

                    try:
                        child_node["size"] = (
                            child.stat().st_size
                        )
                    except OSError:
                        child_node["size"] = None

                node["children"].append(child_node)

                if truncated:
                    break

            return node

        tree = build_tree(
            target,
            current_depth=0,
        )

        return {
            "path": self._relative_path(target),
            "tree": tree,
            "total_entries": total_entries,
            "truncated": truncated,
        }