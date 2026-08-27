import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://localhost:8443/mcp"

# 테스트 코드가 Harness 역할을 대신한다.
WORKSPACE_ROOT = str(
    Path(__file__).resolve().parents[1]
)


def print_tool_result(result) -> None:
    print("\n========== RESULT ==========")

    for content in result.content:
        if hasattr(content, "text"):
            print(content.text)
        else:
            print(content)

    print("============================")


async def main():
    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")

    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            await session.initialize()

            print("\n[MCP] 연결 성공")

            # -------------------------------------------------
            # Tool 목록 확인
            # -------------------------------------------------
            tools_result = await session.list_tools()

            print("\n========== MCP TOOLS ==========")

            for tool in tools_result.tools:
                print(f"\nTool: {tool.name}")
                print(
                    json.dumps(
                        tool.input_schema,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

            # -------------------------------------------------
            # list_files
            # -------------------------------------------------
            print("\n\n>>> list_files 테스트")

            result = await session.call_tool(
                "list_files",
                arguments={
                    "workspace_root": WORKSPACE_ROOT,
                    "path": ".",
                    "include_hidden": False,
                    "max_entries": 100,
                },
            )

            print_tool_result(result)

            # -------------------------------------------------
            # get_project_tree
            # -------------------------------------------------
            print("\n\n>>> get_project_tree 테스트")

            result = await session.call_tool(
                "get_project_tree",
                arguments={
                    "workspace_root": WORKSPACE_ROOT,
                    "path": ".",
                    "max_depth": 2,
                    "include_hidden": False,
                    "max_entries": 100,
                },
            )

            print_tool_result(result)


if __name__ == "__main__":
    asyncio.run(main())