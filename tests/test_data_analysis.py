import asyncio
import json
import tempfile
from pathlib import Path

import pandas as pd

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://localhost:8443/mcp"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def print_tool_result(result) -> None:
    print("\n========== RESULT ==========")

    for content in result.content:
        if hasattr(content, "text"):
            print(content.text)
        else:
            print(content)

    print("============================")


def create_test_files(directory: Path) -> dict[str, str]:
    dataframe = pd.DataFrame(
        {
            "id": [1, 2, 2, 4],
            "name": ["alpha", "beta", None, "delta"],
            "amount": [10.5, None, 10.5, 40.0],
        }
    )

    parquet_path = directory / "sample.parquet"
    csv_path = directory / "sample.csv"
    xlsx_path = directory / "sample.xlsx"

    dataframe.to_parquet(
        parquet_path,
        engine="pyarrow",
        index=False,
    )
    dataframe.to_csv(
        csv_path,
        index=False,
    )

    with pd.ExcelWriter(
        xlsx_path,
        engine="openpyxl",
    ) as writer:
        dataframe.to_excel(
            writer,
            sheet_name="Data",
            index=False,
        )
        dataframe[["id"]].to_excel(
            writer,
            sheet_name="Ids",
            index=False,
        )

    return {
        "parquet": parquet_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "csv": csv_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
        "xlsx": xlsx_path.relative_to(
            WORKSPACE_ROOT
        ).as_posix(),
    }


async def call_inspect_table(
    session: ClientSession,
    path: str,
    sheet_name: str | None = None,
) -> None:
    arguments = {
        "workspace_root": str(WORKSPACE_ROOT),
        "path": path,
    }

    if sheet_name is not None:
        arguments["sheet_name"] = sheet_name

    print(f"\n\n>>> inspect_table 테스트: {path}")

    result = await session.call_tool(
        "inspect_table",
        arguments=arguments,
    )

    print_tool_result(result)


async def call_preview_rows(
    session: ClientSession,
    path: str,
    columns: list[str] | None = None,
    n: int = 20,
    mode: str = "head",
    sheet_name: str | None = None,
) -> None:
    arguments = {
        "workspace_root": str(WORKSPACE_ROOT),
        "path": path,
        "n": n,
        "mode": mode,
    }

    if columns is not None:
        arguments["columns"] = columns

    if sheet_name is not None:
        arguments["sheet_name"] = sheet_name

    print(
        f"\n\n>>> preview_rows 테스트: "
        f"{path} ({mode})"
    )

    result = await session.call_tool(
        "preview_rows",
        arguments=arguments,
    )

    print_tool_result(result)


async def main():
    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")

    with tempfile.TemporaryDirectory(
        prefix="data_analysis_test_",
        dir=WORKSPACE_ROOT,
    ) as temporary_directory:
        paths = create_test_files(
            Path(temporary_directory)
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

                print("\n[MCP] 연결 성공")

                tools_result = await session.list_tools()
                inspect_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "inspect_table"
                )

                print("\n========== inspect_table ==========")
                print(
                    json.dumps(
                        inspect_tool.input_schema,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                preview_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "preview_rows"
                )

                print("\n========== preview_rows ==========")
                print(
                    json.dumps(
                        preview_tool.input_schema,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                await call_inspect_table(
                    session,
                    paths["parquet"],
                )
                await call_inspect_table(
                    session,
                    paths["csv"],
                )
                await call_inspect_table(
                    session,
                    paths["xlsx"],
                )
                await call_inspect_table(
                    session,
                    paths["xlsx"],
                    sheet_name="Ids",
                )

                await call_preview_rows(
                    session,
                    paths["parquet"],
                    n=2,
                    mode="head",
                )
                await call_preview_rows(
                    session,
                    paths["csv"],
                    columns=["id", "name"],
                    n=2,
                    mode="tail",
                )
                await call_preview_rows(
                    session,
                    paths["xlsx"],
                    columns=["id"],
                    n=2,
                    mode="random",
                    sheet_name="Ids",
                )


if __name__ == "__main__":
    asyncio.run(main())
