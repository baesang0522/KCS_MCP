import asyncio
import json
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from test_agent import convert_mcp_tools_for_agent


MCP_URL = "http://localhost:8443/mcp"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "jupyter-code-edit-mcp-test"


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


async def call_write_jupyter_code_cell(
    session: ClientSession,
    notebook_path: str,
    mode: str,
    source: str,
    **arguments,
) -> dict:
    result = await session.call_tool(
        "write_jupyter_code_cell",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "task_id": TASK_ID,
            "notebook_path": notebook_path,
            "mode": mode,
            "source": source,
            **arguments,
        },
    )

    return result_to_dict(result)


async def assert_tool_error(
    session: ClientSession,
    name: str,
    notebook_path: str,
    **arguments,
) -> None:
    result = await session.call_tool(
        "write_jupyter_code_cell",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "task_id": TASK_ID,
            "notebook_path": notebook_path,
            "mode": "create",
            "source": "print('test')",
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
            prefix="jupyter_code_edit_test_",
            dir=WORKSPACE_ROOT,
        ) as workspace_directory,
        tempfile.TemporaryDirectory(
            prefix="jupyter_code_edit_outside_",
        ) as outside_directory,
    ):
        workspace = Path(workspace_directory)
        outside = Path(outside_directory)
        notebook = workspace / "analysis.ipynb"
        notebook.write_text(
            json.dumps(
                {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 5,
                }
            ),
            encoding="utf-8",
        )
        notebook_bytes = notebook.read_bytes()

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
                jupyter_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "write_jupyter_code_cell"
                )
                assert set(
                    jupyter_tool.input_schema["properties"]
                ) == {
                    "workspace_root",
                    "task_id",
                    "notebook_path",
                    "mode",
                    "source",
                    "target_cell_id",
                    "expected_source_hash",
                }

                agent_tools = convert_mcp_tools_for_agent(
                    tools_result.tools
                )
                agent_tool = next(
                    tool
                    for tool in agent_tools
                    if tool["function"]["name"]
                    == "write_jupyter_code_cell"
                )
                agent_schema = agent_tool[
                    "function"
                ]["parameters"]
                assert set(agent_schema["properties"]) == {
                    "mode",
                    "source",
                    "target_cell_id",
                    "expected_source_hash",
                }
                assert set(agent_schema["required"]) == {
                    "mode",
                    "source",
                }
                print("[PASS] MCP 등록 및 Harness 인자 schema 숨김")

                expected_hash = "A" * 64
                revise = await call_write_jupyter_code_cell(
                    session=session,
                    notebook_path=relative_path(notebook),
                    mode="revise",
                    source="def revised():\n    return 2\n",
                    target_cell_id="target-cell-id",
                    expected_source_hash=expected_hash,
                )
                assert revise["operation"] == (
                    "jupyter_code_cell_action"
                )
                assert revise["executed"] is False
                assert revise["action"] == {
                    "action_id": revise["action"]["action_id"],
                    "type": "write_jupyter_code_cell",
                    "task_id": TASK_ID,
                    "notebook_path": relative_path(notebook),
                    "mode": "revise",
                    "source": "def revised():\n    return 2\n",
                    "target_cell_id": "target-cell-id",
                    "expected_source_hash": expected_hash.lower(),
                }
                assert len(revise["action"]["action_id"]) == 32
                int(revise["action"]["action_id"], 16)
                assert notebook.read_bytes() == notebook_bytes
                print("[PASS] revise action 생성 및 raw Notebook 무변경")

                create = await call_write_jupyter_code_cell(
                    session=session,
                    notebook_path=relative_path(notebook),
                    mode="create",
                    source="class Created:\n    pass\n",
                )
                assert create["executed"] is False
                assert create["action"]["mode"] == "create"
                assert create["action"]["target_cell_id"] is None
                assert create["action"][
                    "expected_source_hash"
                ] is None
                assert notebook.read_bytes() == notebook_bytes
                print("[PASS] create action 생성 및 자동 실행 없음")

                await assert_tool_error(
                    session,
                    "revise target_cell_id 필수",
                    relative_path(notebook),
                    mode="revise",
                )
                await assert_tool_error(
                    session,
                    "잘못된 source hash 형식",
                    relative_path(notebook),
                    mode="revise",
                    target_cell_id="target",
                    expected_source_hash="invalid",
                )

                text_file = workspace / "analysis.py"
                text_file.write_text(
                    "print('test')\n",
                    encoding="utf-8",
                )
                await assert_tool_error(
                    session,
                    ".ipynb 외 경로 거부",
                    relative_path(text_file),
                )
                await assert_tool_error(
                    session,
                    "절대경로 거부",
                    str(notebook),
                )
                await assert_tool_error(
                    session,
                    "workspace 탈출 거부",
                    "../outside.ipynb",
                )

                outside_notebook = outside / "outside.ipynb"
                outside_notebook.write_text(
                    "{}",
                    encoding="utf-8",
                )
                outside_link = workspace / "outside_link.ipynb"
                outside_link.symlink_to(outside_notebook)
                await assert_tool_error(
                    session,
                    "workspace 밖 symbolic link 거부",
                    relative_path(outside_link),
                )

                inside_link = workspace / "inside_link.ipynb"
                inside_link.symlink_to(notebook)
                await assert_tool_error(
                    session,
                    "workspace 내부 symbolic link 거부",
                    relative_path(inside_link),
                )
                assert notebook.read_bytes() == notebook_bytes


if __name__ == "__main__":
    asyncio.run(main())
