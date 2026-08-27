import asyncio
import copy
import json
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
# 지금 테스트에서는 KCS_MCP 프로젝트를 workspace로 사용
# ------------------------------------------------------------

WORKSPACE_ROOT = str(
    Path(__file__).resolve().parents[1]
)


llm = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
)


def convert_mcp_tools_for_agent(
    mcp_tools,
) -> list[dict[str, Any]]:
    """
    MCP Tool schema를 Agent에게 전달할 schema로 변환한다.

    workspace_root는 Harness가 관리하는 값이므로
    LLM에게 노출하지 않는다.
    """

    converted_tools = []

    for tool in mcp_tools:

        schema = copy.deepcopy(tool.input_schema)

        properties = schema.get(
            "properties",
            {},
        )

        # workspace_root를 LLM schema에서 제거
        properties.pop(
            "workspace_root",
            None,
        )

        required = schema.get(
            "required",
            [],
        )

        schema["required"] = [
            item
            for item in required
            if item != "workspace_root"
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
            # Agent에게는 workspace_root 제거
            # ------------------------------------------------

            agent_tools = (
                convert_mcp_tools_for_agent(
                    mcp_tools
                )
            )

            print(
                "\n[Harness] "
                "workspace_root를 "
                "Agent Tool schema에서 제거"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a coding agent. "
                        "Use the provided tools to inspect "
                        "the user's project when necessary. "
                        "Do not guess the project structure. "
                        "Use tools when you need information "
                        "about files or directories. "
                        "Answer in Korean."
                    ),
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

                messages.append(
                    {
                        "role": "user",
                        "content": user_input,
                    }
                )

                # --------------------------------------------
                # Agent loop
                # --------------------------------------------

                while True:

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
                            f"{message.content}"
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

                        arguments = json.loads(
                            tool_call
                            .function
                            .arguments
                        )

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
                        # ★ Harness가 workspace_root 삽입
                        # ====================================

                        mcp_arguments = {
                            "workspace_root":
                                WORKSPACE_ROOT,
                            **arguments,
                        }

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

                        result = (
                            await session.call_tool(
                                tool_name,
                                arguments=mcp_arguments,
                            )
                        )

                        result_text = (
                            result_to_text(result)
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