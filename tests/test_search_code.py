import asyncio
import json
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://localhost:8443/mcp"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def result_to_dict(result) -> dict:
    if result.is_error:
        raise AssertionError(
            f"Tool 호출이 실패했습니다: {result}"
        )

    for content in result.content:
        if hasattr(content, "text"):
            return json.loads(content.text)

    raise AssertionError(
        "Tool 결과에 JSON text content가 없습니다."
    )


async def call_search_code(
    session: ClientSession,
    query: str,
    path: str,
    **arguments,
) -> dict:
    result = await session.call_tool(
        "search_code",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "query": query,
            "path": path,
            **arguments,
        },
    )

    return result_to_dict(result)


def create_test_files(
    workspace_directory: Path,
    outside_directory: Path,
) -> dict[str, str]:
    source_directory = workspace_directory / "src"
    nested_directory = source_directory / "nested"
    many_directory = workspace_directory / "many"

    nested_directory.mkdir(parents=True)
    many_directory.mkdir()

    (source_directory / "auth_service.py").write_text(
        "def validate_token(token):\n"
        "    return token\n",
        encoding="utf-8",
    )
    (nested_directory / "helper.py").write_text(
        "VALIDATE_TOKEN = 'helper'\n",
        encoding="utf-8",
    )
    (nested_directory / "settings.yaml").write_text(
        "validate_token: enabled\n",
        encoding="utf-8",
    )
    (many_directory / "matches.py").write_text(
        "needle one\n"
        "needle two\n"
        "needle three\n"
        "needle four\n",
        encoding="utf-8",
    )

    ignored_directories = [
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
    ]

    for directory_name in ignored_directories:
        ignored_directory = (
            workspace_directory / directory_name
        )
        ignored_directory.mkdir()
        (ignored_directory / "ignored.py").write_text(
            "excluded_marker\n",
            encoding="utf-8",
        )

    (workspace_directory / ".hidden.py").write_text(
        "excluded_marker\n",
        encoding="utf-8",
    )
    (workspace_directory / "sample.ipynb").write_text(
        '{"source": ["excluded_marker"]}\n',
        encoding="utf-8",
    )
    (workspace_directory / "binary.bin").write_bytes(
        b"excluded_marker\n\x00binary"
    )
    (workspace_directory / "non_utf8.txt").write_bytes(
        b"excluded_marker\ninvalid\xfftext"
    )

    outside_file = outside_directory / "outside.py"
    outside_file.write_text(
        "excluded_marker\n",
        encoding="utf-8",
    )
    (workspace_directory / "outside_link.py").symlink_to(
        outside_file
    )

    return {
        "root": workspace_directory.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "source": source_directory.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "many": many_directory.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
    }


async def main():
    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")

    with (
        tempfile.TemporaryDirectory(
            prefix="search_code_test_",
            dir=WORKSPACE_ROOT,
        ) as workspace_directory,
        tempfile.TemporaryDirectory(
            prefix="search_code_outside_",
        ) as outside_directory,
    ):
        paths = create_test_files(
            workspace_directory=Path(
                workspace_directory
            ),
            outside_directory=Path(
                outside_directory
            ),
        )

        async with streamable_http_client(MCP_URL) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(
                read_stream,
                write_stream,
            ) as session:
                await session.initialize()

                tools_result = await session.list_tools()
                search_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "search_code"
                )

                print("\n========== search_code ==========")
                print(
                    json.dumps(
                        search_tool.input_schema,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                normal = await call_search_code(
                    session,
                    query="validate_token",
                    path=paths["source"],
                )
                assert len(normal["results"]) == 3
                assert normal["truncated"] is False
                assert all(
                    set(result) == {
                        "path",
                        "line",
                        "content",
                    }
                    for result in normal["results"]
                )
                print("[PASS] 정상 검색")

                result_paths = {
                    result["path"]
                    for result in normal["results"]
                }
                assert any(
                    path.endswith("nested/helper.py")
                    for path in result_paths
                )
                assert any(
                    path.endswith("nested/settings.yaml")
                    for path in result_paths
                )
                print("[PASS] 하위 디렉토리 재귀 검색")

                case_insensitive = await call_search_code(
                    session,
                    query="VALIDATE_TOKEN",
                    path=paths["source"],
                )
                assert len(case_insensitive["results"]) == 3
                print("[PASS] 대소문자 비구분 검색")

                python_only = await call_search_code(
                    session,
                    query="validate_token",
                    path=paths["source"],
                    file_pattern="*.py",
                )
                assert len(python_only["results"]) == 2
                assert all(
                    result["path"].endswith(".py")
                    for result in python_only["results"]
                )
                print("[PASS] file_pattern")

                limited = await call_search_code(
                    session,
                    query="needle",
                    path=paths["many"],
                    max_results=2,
                )
                assert len(limited["results"]) == 2
                assert limited["truncated"] is True
                print("[PASS] max_results 잘림")

                excluded = await call_search_code(
                    session,
                    query="excluded_marker",
                    path=paths["root"],
                )
                assert excluded["results"] == []
                assert excluded["truncated"] is False
                print("[PASS] ignore/binary/ipynb/비 UTF-8 제외")

                outside_result = await session.call_tool(
                    "search_code",
                    arguments={
                        "workspace_root": str(WORKSPACE_ROOT),
                        "query": "anything",
                        "path": "..",
                    },
                )
                assert outside_result.is_error
                print("[PASS] workspace 탈출 차단")


if __name__ == "__main__":
    asyncio.run(main())
