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


async def call_read_file(
    session: ClientSession,
    path: str,
    **arguments,
) -> dict:
    result = await session.call_tool(
        "read_file",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "path": path,
            **arguments,
        },
    )

    return result_to_dict(result)


async def assert_read_error(
    session: ClientSession,
    name: str,
    path: str,
    **arguments,
) -> None:
    result = await session.call_tool(
        "read_file",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "path": path,
            **arguments,
        },
    )

    if not result.is_error:
        raise AssertionError(
            f"{name}: 오류가 발생하지 않았습니다."
        )

    print(f"[PASS] {name}")


def create_test_files(
    workspace_directory: Path,
    outside_directory: Path,
) -> dict[str, str]:
    normal_content = (
        "첫째 줄\n"
        "둘째 줄\n"
        "셋째 줄\n"
        "넷째 줄\n"
    )
    normal_path = workspace_directory / "normal.txt"
    normal_path.write_text(
        normal_content,
        encoding="utf-8",
        newline="",
    )

    large_path = workspace_directory / "large.txt"

    with large_path.open(
        mode="w",
        encoding="utf-8",
        newline="",
    ) as file:
        for line_number in range(1, 25001):
            file.write(
                f"line {line_number:05d}\n"
            )

    binary_path = workspace_directory / "binary.bin"
    binary_path.write_bytes(
        b"binary\x00content"
    )

    non_utf8_path = workspace_directory / "non_utf8.txt"
    non_utf8_path.write_bytes(
        b"text\xffcontent"
    )

    invalid_tail_path = (
        workspace_directory / "invalid_tail.txt"
    )
    invalid_tail_path.write_bytes(
        b"first line\nsecond line\ninvalid\xfftail"
    )

    long_line_path = workspace_directory / "long_line.txt"
    long_line_path.write_text(
        "x" * 100 + "\n",
        encoding="utf-8",
    )

    notebook_path = workspace_directory / "sample.ipynb"
    notebook_path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    outside_path = outside_directory / "outside.txt"
    outside_path.write_text(
        "outside\n",
        encoding="utf-8",
    )

    symlink_path = workspace_directory / "outside_link.txt"
    symlink_path.symlink_to(outside_path)

    return {
        "directory": workspace_directory.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "normal": normal_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "large": large_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "binary": binary_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "non_utf8": non_utf8_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "invalid_tail": invalid_tail_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "long_line": long_line_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "notebook": notebook_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "symlink": symlink_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
    }


async def main():
    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")

    with (
        tempfile.TemporaryDirectory(
            prefix="read_file_test_",
            dir=WORKSPACE_ROOT,
        ) as workspace_directory,
        tempfile.TemporaryDirectory(
            prefix="read_file_outside_",
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
                read_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "read_file"
                )

                print("\n========== read_file ==========")
                print(
                    json.dumps(
                        read_tool.input_schema,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                normal = await call_read_file(
                    session,
                    paths["normal"],
                )
                assert normal["content"] == (
                    "첫째 줄\n둘째 줄\n셋째 줄\n넷째 줄\n"
                )
                assert normal["start_line"] == 1
                assert normal["end_line"] == 4
                assert normal["file_size"] == (
                    WORKSPACE_ROOT / paths["normal"]
                ).stat().st_size
                assert "total_lines" not in normal
                assert "total_chars" not in normal
                assert normal["truncated"] is False
                assert "next_start_line" not in normal
                print("[PASS] 정상 읽기")

                bounded = await call_read_file(
                    session,
                    paths["invalid_tail"],
                    end_line=2,
                )
                assert bounded["content"] == (
                    "first line\nsecond line\n"
                )
                assert bounded["end_line"] == 2
                assert bounded["truncated"] is False
                print("[PASS] 요청 범위 이후를 스캔하지 않음")

                partial = await call_read_file(
                    session,
                    paths["normal"],
                    start_line=2,
                    end_line=3,
                )
                assert partial["content"] == (
                    "둘째 줄\n셋째 줄\n"
                )
                assert partial["start_line"] == 2
                assert partial["end_line"] == 3
                assert partial["truncated"] is False
                print("[PASS] 부분 읽기")

                large = await call_read_file(
                    session,
                    paths["large"],
                    max_lines=10,
                    max_chars=20000,
                )
                assert large["file_size"] == 25000 * 11
                assert large["end_line"] == 10
                assert large["truncated"] is True
                assert large["next_start_line"] == 11
                print("[PASS] 대용량 max_lines 잘림")

                large_continuation = await call_read_file(
                    session,
                    paths["large"],
                    start_line=large["next_start_line"],
                    max_lines=10,
                    max_chars=20000,
                )
                assert large_continuation["content"].startswith(
                    "line 00011\n"
                )
                assert large_continuation["end_line"] == 20
                assert large_continuation[
                    "next_start_line"
                ] == 21
                print("[PASS] 대용량 continuation")

                char_page_1 = await call_read_file(
                    session,
                    paths["normal"],
                    max_chars=6,
                )
                assert char_page_1["content"] == "첫째 줄\n"
                assert char_page_1["end_line"] == 1
                assert char_page_1["truncated"] is True
                assert char_page_1["next_start_line"] == 2

                char_page_2 = await call_read_file(
                    session,
                    paths["normal"],
                    start_line=char_page_1[
                        "next_start_line"
                    ],
                    max_chars=6,
                )
                assert char_page_2["content"] == "둘째 줄\n"
                assert (
                    char_page_1["content"]
                    + char_page_2["content"]
                    == "첫째 줄\n둘째 줄\n"
                )
                print("[PASS] max_chars line 단위 continuation")

                await assert_read_error(
                    session,
                    "잘못된 경로",
                    "missing.txt",
                )
                await assert_read_error(
                    session,
                    "workspace 밖 .. 접근",
                    "../outside.txt",
                )
                await assert_read_error(
                    session,
                    "workspace 밖 symlink 접근",
                    paths["symlink"],
                )
                await assert_read_error(
                    session,
                    "디렉토리 거부",
                    paths["directory"],
                )
                await assert_read_error(
                    session,
                    "binary 거부",
                    paths["binary"],
                )
                await assert_read_error(
                    session,
                    "비 UTF-8 거부",
                    paths["non_utf8"],
                )
                await assert_read_error(
                    session,
                    "max_chars보다 긴 단일 line 거부",
                    paths["long_line"],
                    max_chars=20,
                )
                await assert_read_error(
                    session,
                    "ipynb 거부",
                    paths["notebook"],
                )


if __name__ == "__main__":
    asyncio.run(main())
