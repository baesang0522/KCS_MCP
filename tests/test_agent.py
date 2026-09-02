import asyncio
import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

from openai import OpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "gemma4:e2b"

MCP_URL = "http://localhost:8443/mcp"


# ------------------------------------------------------------
# 실제 환경에서는 Jupyter/Agent Harness가 결정할 값
# 현재 테스트에서는 KCS_MCP 프로젝트를 workspace로 사용
# ------------------------------------------------------------

WORKSPACE_ROOT = str(
    Path(__file__).resolve().parents[1]
)
TASK_ID = uuid.uuid4().hex
NOTEBOOK_PATH = os.environ.get(
    "AGENT_NOTEBOOK_PATH",
    "",
)


# workspace_root를 Harness가 자동으로 주입할 Tool
WORKSPACE_TOOLS = {
    "list_files",
    "read_file",
    "search_code",
    "get_project_tree",
    "write_file",
    "apply_patch",
    "write_jupyter_code_cell",
}


# task_id를 Harness가 자동으로 주입할 Tool
TASK_TOOLS = {
    "apply_patch",
    "write_jupyter_code_cell",
}


# notebook_path를 Harness가 자동으로 주입할 Tool
NOTEBOOK_TOOLS = {
    "write_jupyter_code_cell",
}


HARNESS_ARGUMENTS = {
    "workspace_root",
    "task_id",
    "notebook_path",
}


llm = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
)


SYSTEM_PROMPT = """
당신은 코드 분석 Agent입니다.

프로젝트의 실제 상태를 확인해야 하는 요청에서는 추측하지 말고
반드시 제공된 Tool을 사용하여 확인하세요.

중요 규칙:
- 제공된 Tool 이름만 호출하세요.
- 존재하지 않는 Tool 이름을 임의로 만들지 마세요.
- inspect, browse, explore 같은 Tool을 임의로 생성하지 마세요.
- 사용자에게 파일이나 코드를 보여달라고 요청하기 전에
  먼저 사용할 수 있는 Tool로 직접 조사하세요.
- 과거 대화에서 프로젝트를 확인했더라도 사용자가 다시 확인하라고 하면
  현재 Tool을 사용하여 다시 확인하세요.
- 파일명이나 디렉토리명만 보고 코드 동작을 확정하지 마세요.

파일 탐색 Tool 사용 기준:
- get_project_tree:
  처음 보는 프로젝트의 전체 구조를 확인할 때 사용합니다.
- list_files:
  특정 디렉토리 바로 아래의 파일을 확인할 때 사용합니다.
- search_code:
  함수명, 클래스명, 문자열 등 실제 구현 위치를 찾을 때 사용합니다.
- read_file:
  확인된 파일의 실제 코드 내용을 읽을 때 사용합니다.

예:
사용자가 "프로젝트 구조를 파악해줘"라고 하면
get_project_tree 사용을 우선 고려하세요.

사용자가 "디렉토리 트리 만드는 코드를 수정하고 싶다"고 하면
search_code로 get_project_tree 구현 위치를 찾고,
필요하면 read_file로 실제 구현 내용을 확인하세요.

한국어로 답변하세요.
""".strip()


def convert_mcp_tools_for_agent(
    mcp_tools,
) -> list[dict[str, Any]]:
    """
    MCP Tool schema를 LLM에게 전달할 OpenAI Tool schema로 변환합니다.

    workspace_root, task_id, notebook_path는 Agent가 결정하는 값이 아니라
    Harness가 관리하는 실행 컨텍스트이므로 LLM에게 노출하지 않습니다.

    Args:
        mcp_tools:
            MCP 서버에서 조회한 Tool 목록입니다.

    Returns:
        OpenAI-compatible function calling 형식으로 변환한 Tool 목록입니다.
    """
    converted_tools = []

    for tool in mcp_tools:
        schema = copy.deepcopy(
            tool.input_schema
        )

        properties = schema.get(
            "properties",
            {},
        )

        for argument_name in HARNESS_ARGUMENTS:
            properties.pop(
                argument_name,
                None,
            )

        required = schema.get(
            "required",
            [],
        )

        schema["required"] = [
            item
            for item in required
            if item not in HARNESS_ARGUMENTS
        ]

        converted_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (
                        tool.description or ""
                    ),
                    "parameters": schema,
                },
            }
        )

    return converted_tools


def result_to_text(result) -> str:
    """
    MCP Tool 실행 결과를 LLM에 전달할 문자열로 변환합니다.

    Args:
        result:
            MCP ClientSession.call_tool 결과입니다.

    Returns:
        Tool 결과 content를 하나의 문자열로 변환하여 반환합니다.
    """
    texts = []

    for content in result.content:
        if hasattr(content, "text"):
            texts.append(content.text)
        else:
            texts.append(str(content))

    return "\n".join(texts)


async def main():
    print("=" * 60)
    print("KCS MCP Agent Test")
    print("=" * 60)

    print(f"Model          : {OLLAMA_MODEL}")
    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")

    async with streamable_http_client(
        MCP_URL
    ) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            await session.initialize()

            # ------------------------------------------------
            # MCP Tool discovery
            # ------------------------------------------------

            tools_result = (
                await session.list_tools()
            )

            mcp_tools = tools_result.tools

            print(
                f"\n[MCP] "
                f"{len(mcp_tools)}개 Tool 발견"
            )

            for tool in mcp_tools:
                print(f" - {tool.name}")

            # ------------------------------------------------
            # Agent용 Tool schema 생성
            # ------------------------------------------------

            agent_tools = (
                convert_mcp_tools_for_agent(
                    mcp_tools
                )
            )

            valid_tool_names = {
                tool["function"]["name"]
                for tool in agent_tools
            }

            print(
                "\n[Harness] "
                "workspace_root, task_id, notebook_path를 "
                "Agent Tool schema에서 제거"
            )

            print(
                "\n[Tools → LLM]"
            )

            for tool in agent_tools:
                print(
                    f" - "
                    f"{tool['function']['name']}"
                )

            messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                }
            ]

            while True:
                user_input = input(
                    "\nYou > "
                ).strip()

                if user_input.lower() in {
                    "exit",
                    "quit",
                    "/bye",
                }:
                    break

                if not user_input:
                    continue

                messages.append(
                    {
                        "role": "user",
                        "content": user_input,
                    }
                )

                # --------------------------------------------
                # Agent loop
                # --------------------------------------------

                tool_loop_count = 0
                max_tool_loops = 20

                while True:
                    tool_loop_count += 1

                    if (
                        tool_loop_count
                        > max_tool_loops
                    ):
                        print(
                            "\n[Harness] "
                            "Tool 호출 횟수 제한에 "
                            "도달했습니다."
                        )
                        break

                    response = (
                        llm.chat.completions.create(
                            model=OLLAMA_MODEL,
                            messages=messages,
                            tools=agent_tools,
                            tool_choice="auto",
                        )
                    )

                    message = (
                        response
                        .choices[0]
                        .message
                    )

                    # ----------------------------------------
                    # Tool call 없음 → 최종 답변
                    # ----------------------------------------

                    if not message.tool_calls:
                        print(
                            f"\nGemma > "
                            f"{message.content or ''}"
                        )

                        messages.append(
                            {
                                "role": "assistant",
                                "content": (
                                    message.content or ""
                                ),
                            }
                        )

                        break

                    # assistant tool_call message를
                    # history에 그대로 추가
                    messages.append(
                        message.model_dump(
                            exclude_none=True
                        )
                    )

                    # ----------------------------------------
                    # Tool 실행
                    # ----------------------------------------

                    for tool_call in (
                        message.tool_calls
                    ):
                        tool_name = (
                            tool_call
                            .function
                            .name
                        )

                        try:
                            arguments = json.loads(
                                tool_call
                                .function
                                .arguments
                            )
                        except json.JSONDecodeError:
                            arguments = {}

                        print(
                            "\n[LLM → Harness]"
                        )

                        print(
                            f"Tool: {tool_name}"
                        )

                        print(
                            "LLM Arguments:",
                            json.dumps(
                                arguments,
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )

                        # ====================================
                        # 존재하지 않는 Tool 호출 차단
                        # ====================================

                        if (
                            tool_name
                            not in valid_tool_names
                        ):
                            error_message = (
                                f"'{tool_name}'은 "
                                "존재하지 않는 Tool입니다. "
                                "사용 가능한 Tool: "
                                f"{', '.join(sorted(valid_tool_names))}. "
                                "사용자 요청을 다시 수행하고 "
                                "적절한 Tool을 선택하세요."
                            )

                            print(
                                "\n[Harness] "
                                "Unknown Tool 차단"
                            )

                            print(error_message)

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id":
                                        tool_call.id,
                                    "content":
                                        error_message,
                                }
                            )

                            continue

                        # ====================================
                        # MCP 전달용 인자 생성
                        # ====================================

                        mcp_arguments = dict(
                            arguments
                        )

                        # workspace 기반 Tool인 경우에만
                        # Harness가 workspace_root를 강제 주입
                        if (
                            tool_name
                            in WORKSPACE_TOOLS
                        ):
                            mcp_arguments[
                                "workspace_root"
                            ] = WORKSPACE_ROOT

                        if (
                            tool_name
                            in TASK_TOOLS
                        ):
                            mcp_arguments[
                                "task_id"
                            ] = TASK_ID

                        if (
                            tool_name
                            in NOTEBOOK_TOOLS
                        ):
                            mcp_arguments[
                                "notebook_path"
                            ] = NOTEBOOK_PATH

                        print(
                            "\n[Harness → MCP]"
                        )

                        print(
                            "Actual Arguments:",
                            json.dumps(
                                mcp_arguments,
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )

                        # ------------------------------------
                        # MCP 호출
                        # ------------------------------------

                        try:
                            result = (
                                await session.call_tool(
                                    tool_name,
                                    arguments=mcp_arguments,
                                )
                            )

                            result_text = (
                                result_to_text(
                                    result
                                )
                            )

                        except Exception as exc:
                            result_text = (
                                "Tool 실행 중 오류가 "
                                "발생했습니다: "
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            )

                        print(
                            "\n[MCP → Harness]"
                        )

                        print(result_text)

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id":
                                    tool_call.id,
                                "content":
                                    result_text,
                            }
                        )


if __name__ == "__main__":
    asyncio.run(main())
