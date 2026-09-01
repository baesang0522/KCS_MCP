import asyncio
import json
import stat
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


async def call_write_file(
    session: ClientSession,
    path: str,
    content: str,
    **arguments,
) -> dict:
    result = await session.call_tool(
        "write_file",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "path": path,
            "content": content,
            **arguments,
        },
    )

    return result_to_dict(result)


async def assert_write_error(
    session: ClientSession,
    name: str,
    path: str,
    content: str = "test\n",
    **arguments,
) -> None:
    result = await session.call_tool(
        "write_file",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "path": path,
            "content": content,
            **arguments,
        },
    )

    if not result.is_error:
        raise AssertionError(
            f"{name}: 오류가 발생하지 않았습니다."
        )

    print(f"[PASS] {name}")


def relative_path(path: Path) -> str:
    return path.relative_to(WORKSPACE_ROOT).as_posix()


async def main():
    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")

    with (
        tempfile.TemporaryDirectory(
            prefix="write_file_test_",
            dir=WORKSPACE_ROOT,
        ) as workspace_directory,
        tempfile.TemporaryDirectory(
            prefix="write_file_outside_",
        ) as outside_directory,
    ):
        workspace = Path(workspace_directory)
        outside = Path(outside_directory)
        workspace_path = relative_path(workspace)

        existing_path = workspace / "existing.py"
        existing_path.write_text(
            "old content\n",
            encoding="utf-8",
            newline="",
        )
        existing_path.chmod(0o755)

        binary_path = workspace / "binary.bin"
        binary_path.write_bytes(b"binary\x00content")

        non_utf8_path = workspace / "non_utf8.txt"
        non_utf8_path.write_bytes(b"text\xffcontent")

        directory_path = workspace / "directory"
        directory_path.mkdir()

        outside_file = outside / "outside.py"
        outside_file.write_text(
            "outside\n",
            encoding="utf-8",
        )
        outside_link = workspace / "outside_link.py"
        outside_link.symlink_to(outside_file)

        real_directory = workspace / "real_directory"
        real_directory.mkdir()
        inside_link = workspace / "inside_link"
        inside_link.symlink_to(
            real_directory,
            target_is_directory=True,
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
                write_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "write_file"
                )

                print("\n========== write_file ==========")
                print(
                    json.dumps(
                        write_tool.input_schema,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                new_path = workspace / "new_file.py"
                new_content = "def 인사():\r\n    return '안녕'\r\n"
                created = await call_write_file(
                    session,
                    path=relative_path(new_path),
                    content=new_content,
                )
                assert created == {
                    "path": relative_path(new_path),
                    "operation": "created",
                    "chars_written": len(new_content),
                    "bytes_written": len(
                        new_content.encode("utf-8")
                    ),
                }
                assert new_path.read_bytes() == (
                    new_content.encode("utf-8")
                )
                print("[PASS] 새 UTF-8 파일 생성 및 개행 보존")

                nested_path = (
                    workspace / "new" / "package" / "module.py"
                )
                nested = await call_write_file(
                    session,
                    path=relative_path(nested_path),
                    content="VALUE = 1\n",
                    create_parent_dirs=True,
                )
                assert nested["operation"] == "created"
                assert nested_path.read_text(
                    encoding="utf-8"
                ) == "VALUE = 1\n"
                print("[PASS] 부모 디렉토리와 파일 생성")

                await assert_write_error(
                    session,
                    "부모 디렉토리 자동 생성 비활성화",
                    path=(
                        f"{workspace_path}/missing/module.py"
                    ),
                )

                await assert_write_error(
                    session,
                    "기존 파일 기본 덮어쓰기 차단",
                    path=relative_path(existing_path),
                    content="new content\n",
                )

                overwritten = await call_write_file(
                    session,
                    path=relative_path(existing_path),
                    content="new content\n",
                    overwrite=True,
                )
                assert overwritten["operation"] == "overwritten"
                assert existing_path.read_text(
                    encoding="utf-8"
                ) == "new content\n"
                assert stat.S_IMODE(
                    existing_path.stat().st_mode
                ) == 0o755
                print("[PASS] 기존 파일 전체 교체 및 권한 보존")

                unchanged = await call_write_file(
                    session,
                    path=relative_path(existing_path),
                    content="new content\n",
                    overwrite=True,
                )
                assert unchanged["operation"] == "unchanged"
                assert unchanged["chars_written"] == 0
                assert unchanged["bytes_written"] == 0
                print("[PASS] 동일한 내용은 다시 쓰지 않음")

                hidden_path = (
                    workspace / ".github" / "workflows" / "test.yaml"
                )
                hidden = await call_write_file(
                    session,
                    path=relative_path(hidden_path),
                    content="name: test\n",
                    create_parent_dirs=True,
                )
                assert hidden["operation"] == "created"
                print("[PASS] 일반 숨김 경로 쓰기 허용")

                await assert_write_error(
                    session,
                    "절대경로 차단",
                    path=str(workspace / "absolute.py"),
                )
                await assert_write_error(
                    session,
                    "workspace 밖 .. 접근 차단",
                    path="../outside.py",
                )
                await assert_write_error(
                    session,
                    "workspace 내부 .. 경로도 차단",
                    path=f"{workspace_path}/new/../traversal.py",
                )
                await assert_write_error(
                    session,
                    "workspace 밖 symbolic link 차단",
                    path=relative_path(outside_link),
                    overwrite=True,
                )
                await assert_write_error(
                    session,
                    "workspace 내부 symbolic link 차단",
                    path=(
                        f"{relative_path(inside_link)}/module.py"
                    ),
                )
                await assert_write_error(
                    session,
                    "보호된 디렉토리 쓰기 차단",
                    path=f"{workspace_path}/.git/config",
                    create_parent_dirs=True,
                )
                await assert_write_error(
                    session,
                    "binary 파일 덮어쓰기 차단",
                    path=relative_path(binary_path),
                    overwrite=True,
                )
                await assert_write_error(
                    session,
                    "비 UTF-8 파일 덮어쓰기 차단",
                    path=relative_path(non_utf8_path),
                    overwrite=True,
                )
                await assert_write_error(
                    session,
                    ".ipynb 쓰기 차단",
                    path=f"{workspace_path}/sample.ipynb",
                )
                await assert_write_error(
                    session,
                    "디렉토리 경로 쓰기 차단",
                    path=relative_path(directory_path),
                    overwrite=True,
                )
                await assert_write_error(
                    session,
                    "제어문자 content 차단",
                    path=f"{workspace_path}/control.txt",
                    content="text\x00content",
                )
                await assert_write_error(
                    session,
                    "최대 content 크기 제한",
                    path=f"{workspace_path}/too_large.txt",
                    content="x" * 1_000_001,
                )


if __name__ == "__main__":
    asyncio.run(main())
