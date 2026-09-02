import asyncio
import hashlib
import json
import os
import stat
import tempfile
import threading
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from test_agent import convert_mcp_tools_for_agent


MCP_URL = "http://localhost:8443/mcp"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "apply-patch-mcp-test"


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


async def call_apply_patch(
    session: ClientSession,
    path: str,
    edits: list[dict[str, str]],
) -> dict:
    result = await session.call_tool(
        "apply_patch",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "task_id": TASK_ID,
            "path": path,
            "edits": edits,
        },
    )

    return result_to_dict(result)


async def call_apply_patch_error(
    session: ClientSession,
    path: str,
    edits: list[dict[str, str]],
):
    result = await session.call_tool(
        "apply_patch",
        arguments={
            "workspace_root": str(WORKSPACE_ROOT),
            "task_id": TASK_ID,
            "path": path,
            "edits": edits,
        },
    )

    if not result.is_error:
        raise AssertionError(
            "오류가 발생하지 않았습니다."
        )

    return result


def relative_path(path: Path) -> str:
    return path.relative_to(WORKSPACE_ROOT).as_posix()


def snapshot_directories(
    snapshot_root: Path,
) -> set[Path]:
    if not snapshot_root.is_dir():
        return set()

    return {
        path
        for path in snapshot_root.iterdir()
        if path.is_dir()
    }


def temporary_patch_files(
    workspace: Path,
) -> list[Path]:
    return list(workspace.rglob(".*.tmp"))


async def assert_patch_failure_is_atomic(
    session: ClientSession,
    name: str,
    target: Path,
    edits: list[dict[str, str]],
    snapshot_root: Path,
    path: str | None = None,
) -> None:
    original_bytes = target.read_bytes()
    snapshots_before = snapshot_directories(
        snapshot_root
    )

    await call_apply_patch_error(
        session=session,
        path=path or relative_path(target),
        edits=edits,
    )

    assert target.read_bytes() == original_bytes
    assert snapshot_directories(
        snapshot_root
    ) == snapshots_before
    print(f"[PASS] {name}")


def assert_snapshot(
    snapshot_root: Path,
    result: dict,
    original_bytes: bytes,
    relative_target: str,
    file_mode: int,
) -> None:
    snapshot_id = result["snapshot_id"]
    snapshot_directory = snapshot_root / snapshot_id
    original_path = snapshot_directory / "original.bin"
    metadata_path = snapshot_directory / "metadata.json"
    metadata = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )

    assert len(snapshot_id) == 32
    int(snapshot_id, 16)
    assert TASK_ID not in snapshot_id
    assert original_path.read_bytes() == original_bytes
    assert metadata == {
        "snapshot_id": snapshot_id,
        "task_id": TASK_ID,
        "path": relative_target,
        "created_at": metadata["created_at"],
        "before_sha256": hashlib.sha256(
            original_bytes
        ).hexdigest(),
        "file_mode": f"0o{file_mode:o}",
    }
    assert metadata["created_at"].endswith("Z")
    assert stat.S_IMODE(
        snapshot_root.stat().st_mode
    ) == 0o700
    assert stat.S_IMODE(
        snapshot_directory.stat().st_mode
    ) == 0o700
    assert stat.S_IMODE(
        original_path.stat().st_mode
    ) == 0o600
    assert stat.S_IMODE(
        metadata_path.stat().st_mode
    ) == 0o600


async def assert_external_change_detected(
    session: ClientSession,
    workspace: Path,
    snapshot_root: Path,
) -> None:
    target = workspace / "external_change.py"
    original_content = (
        b"TARGET = 'old'\n"
        + b"x" * (16 * 1024 * 1024)
        + b"\n"
    )
    external_content = b"EXTERNAL = 'changed'\n"
    target.write_bytes(original_content)
    snapshots_before = snapshot_directories(
        snapshot_root
    )
    changed = threading.Event()

    def change_after_snapshot_starts() -> None:
        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            if (
                snapshot_directories(snapshot_root)
                != snapshots_before
            ):
                target.write_bytes(external_content)
                changed.set()
                return

            time.sleep(0.0005)

    watcher = threading.Thread(
        target=change_after_snapshot_starts,
        daemon=True,
    )
    watcher.start()

    await call_apply_patch_error(
        session=session,
        path=relative_path(target),
        edits=[
            {
                "old_text": "TARGET = 'old'",
                "new_text": "TARGET = 'patched'",
            }
        ],
    )
    watcher.join(timeout=10)

    assert changed.is_set()
    assert target.read_bytes() == external_content
    assert snapshot_directories(
        snapshot_root
    ) == snapshots_before
    print("[PASS] 수정 중 외부 변경 감지 및 덮어쓰기 차단")


async def assert_snapshot_failure_is_atomic(
    session: ClientSession,
    workspace: Path,
    snapshot_root: Path,
) -> None:
    target = workspace / "snapshot_failure.py"
    target.write_text(
        "VALUE = 'old'\n",
        encoding="utf-8",
        newline="",
    )
    original_bytes = target.read_bytes()
    snapshot_backup = snapshot_root.with_name(
        f"{snapshot_root.name}_backup"
    )
    snapshots_before = snapshot_directories(
        snapshot_root
    )

    snapshot_root.rename(snapshot_backup)
    snapshot_root.write_text(
        "snapshot root is unavailable",
        encoding="utf-8",
    )

    try:
        await call_apply_patch_error(
            session=session,
            path=relative_path(target),
            edits=[
                {
                    "old_text": "VALUE = 'old'",
                    "new_text": "VALUE = 'new'",
                }
            ],
        )
    finally:
        snapshot_root.unlink(missing_ok=True)
        snapshot_backup.rename(snapshot_root)

    assert target.read_bytes() == original_bytes
    assert snapshot_directories(
        snapshot_root
    ) == snapshots_before
    print("[PASS] snapshot 저장 실패 시 원본 유지")


async def main():
    snapshot_root_value = os.environ.get(
        "AGENT_SNAPSHOT_ROOT"
    )

    if not snapshot_root_value:
        raise RuntimeError(
            "테스트에 AGENT_SNAPSHOT_ROOT가 필요합니다."
        )

    snapshot_root = Path(
        snapshot_root_value
    ).resolve()
    snapshot_root.mkdir(
        mode=0o700,
        parents=True,
        exist_ok=True,
    )

    print(f"MCP Server     : {MCP_URL}")
    print(f"Workspace Root : {WORKSPACE_ROOT}")
    print(f"Snapshot Root  : {snapshot_root}")

    with (
        tempfile.TemporaryDirectory(
            prefix="apply_patch_test_",
            dir=WORKSPACE_ROOT,
        ) as workspace_directory,
        tempfile.TemporaryDirectory(
            prefix="apply_patch_outside_",
        ) as outside_directory,
    ):
        workspace = Path(workspace_directory)
        outside = Path(outside_directory)

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
                patch_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "apply_patch"
                )
                assert set(
                    patch_tool.input_schema["properties"]
                ) == {
                    "workspace_root",
                    "task_id",
                    "path",
                    "edits",
                }

                agent_tools = convert_mcp_tools_for_agent(
                    tools_result.tools
                )
                agent_patch_tool = next(
                    tool
                    for tool in agent_tools
                    if tool["function"]["name"]
                    == "apply_patch"
                )
                agent_schema = agent_patch_tool[
                    "function"
                ]["parameters"]
                assert set(agent_schema["properties"]) == {
                    "path",
                    "edits",
                }
                assert set(agent_schema["required"]) == {
                    "path",
                    "edits",
                }
                print("[PASS] MCP 등록 및 Harness 인자 schema 숨김")

                single_path = workspace / "single.py"
                single_original = (
                    b"FIRST = 1\r\n"
                    b"VALUE = 'old'\r\n"
                    b"LAST = 3\r\n"
                )
                single_path.write_bytes(single_original)
                single_path.chmod(0o750)
                single_result = await call_apply_patch(
                    session=session,
                    path=relative_path(single_path),
                    edits=[
                        {
                            "old_text": "VALUE = 'old'",
                            "new_text": "VALUE = 'new'",
                        }
                    ],
                )
                single_after = (
                    b"FIRST = 1\r\n"
                    b"VALUE = 'new'\r\n"
                    b"LAST = 3\r\n"
                )
                assert single_path.read_bytes() == single_after
                assert stat.S_IMODE(
                    single_path.stat().st_mode
                ) == 0o750
                assert single_result == {
                    "path": relative_path(single_path),
                    "operation": "patched",
                    "edits_applied": 1,
                    "snapshot_id": single_result[
                        "snapshot_id"
                    ],
                    "before_sha256": hashlib.sha256(
                        single_original
                    ).hexdigest(),
                    "after_sha256": hashlib.sha256(
                        single_after
                    ).hexdigest(),
                    "bytes_written": len(single_after),
                }
                assert_snapshot(
                    snapshot_root=snapshot_root,
                    result=single_result,
                    original_bytes=single_original,
                    relative_target=relative_path(single_path),
                    file_mode=0o750,
                )
                print(
                    "[PASS] 단일 수정, 개행·권한 보존, "
                    "snapshot 원문·metadata·권한"
                )

                multiple_path = workspace / "multiple.py"
                multiple_path.write_text(
                    "FIRST = 1\n"
                    "def old_function():\n"
                    "    return 'old'\n"
                    "LAST = 3\n",
                    encoding="utf-8",
                    newline="",
                )
                multiple_result = await call_apply_patch(
                    session=session,
                    path=relative_path(multiple_path),
                    edits=[
                        {
                            "old_text": "FIRST = 1",
                            "new_text": "FIRST = 10",
                        },
                        {
                            "old_text": (
                                "def old_function():\n"
                                "    return 'old'"
                            ),
                            "new_text": (
                                "def new_function():\n"
                                "    return 'new'"
                            ),
                        },
                    ],
                )
                assert multiple_result["edits_applied"] == 2
                assert multiple_path.read_text(
                    encoding="utf-8"
                ) == (
                    "FIRST = 10\n"
                    "def new_function():\n"
                    "    return 'new'\n"
                    "LAST = 3\n"
                )
                print("[PASS] 다중 및 여러 줄 수정")

                delete_path = workspace / "delete.py"
                delete_path.write_text(
                    "KEEP = 1\nREMOVE = 2\n",
                    encoding="utf-8",
                    newline="",
                )
                await call_apply_patch(
                    session=session,
                    path=relative_path(delete_path),
                    edits=[
                        {
                            "old_text": "REMOVE = 2\n",
                            "new_text": "",
                        }
                    ],
                )
                assert delete_path.read_text(
                    encoding="utf-8"
                ) == "KEEP = 1\n"
                print("[PASS] new_text 빈 문자열 삭제")

                validation_path = workspace / "validation.py"
                validation_path.write_text(
                    "alpha beta beta gamma\n",
                    encoding="utf-8",
                    newline="",
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "old_text 0건 일치 전체 취소",
                    validation_path,
                    [{"old_text": "missing", "new_text": "x"}],
                    snapshot_root,
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "old_text 다중 일치 전체 취소",
                    validation_path,
                    [{"old_text": "beta", "new_text": "x"}],
                    snapshot_root,
                )

                overlap_path = workspace / "overlap.py"
                overlap_path.write_text(
                    "abcdef\n",
                    encoding="utf-8",
                    newline="",
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "겹치는 edit 전체 취소",
                    overlap_path,
                    [
                        {"old_text": "abc", "new_text": "x"},
                        {"old_text": "cde", "new_text": "y"},
                    ],
                    snapshot_root,
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "빈 edits 거부",
                    overlap_path,
                    [],
                    snapshot_root,
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "빈 old_text 거부",
                    overlap_path,
                    [{"old_text": "", "new_text": "x"}],
                    snapshot_root,
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "동일한 old/new 거부",
                    overlap_path,
                    [{"old_text": "abc", "new_text": "abc"}],
                    snapshot_root,
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "중복 edit 거부",
                    overlap_path,
                    [
                        {"old_text": "abc", "new_text": "x"},
                        {"old_text": "abc", "new_text": "x"},
                    ],
                    snapshot_root,
                )

                notebook_path = workspace / "sample.ipynb"
                notebook_path.write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                binary_path = workspace / "binary.bin"
                binary_path.write_bytes(b"old\x00binary")
                non_utf8_path = workspace / "non_utf8.txt"
                non_utf8_path.write_bytes(b"old\xfftext")
                hidden_path = workspace / ".hidden.py"
                hidden_path.write_text(
                    "old\n",
                    encoding="utf-8",
                )
                cache_path = workspace / "__pycache__" / "cache.py"
                cache_path.parent.mkdir()
                cache_path.write_text(
                    "old\n",
                    encoding="utf-8",
                )

                for name, target in [
                    (".ipynb 거부", notebook_path),
                    ("binary 거부", binary_path),
                    ("비 UTF-8 거부", non_utf8_path),
                    ("숨김 경로 거부", hidden_path),
                    ("cache 경로 거부", cache_path),
                ]:
                    await assert_patch_failure_is_atomic(
                        session,
                        name,
                        target,
                        [{"old_text": "old", "new_text": "new"}],
                        snapshot_root,
                    )

                safe_path = workspace / "safe.py"
                safe_path.write_text(
                    "old\n",
                    encoding="utf-8",
                )
                await assert_patch_failure_is_atomic(
                    session,
                    "절대경로 거부",
                    safe_path,
                    [{"old_text": "old", "new_text": "new"}],
                    snapshot_root,
                    path=str(safe_path),
                )
                await assert_patch_failure_is_atomic(
                    session,
                    ".. 경로 거부",
                    safe_path,
                    [{"old_text": "old", "new_text": "new"}],
                    snapshot_root,
                    path="../outside.py",
                )

                outside_path = outside / "outside.py"
                outside_path.write_text(
                    "old\n",
                    encoding="utf-8",
                )
                outside_link = workspace / "outside_link.py"
                outside_link.symlink_to(outside_path)
                await assert_patch_failure_is_atomic(
                    session,
                    "workspace 밖 symbolic link 거부",
                    outside_path,
                    [{"old_text": "old", "new_text": "new"}],
                    snapshot_root,
                    path=relative_path(outside_link),
                )

                inside_target = workspace / "inside_target.py"
                inside_target.write_text(
                    "old\n",
                    encoding="utf-8",
                )
                inside_link = workspace / "inside_link.py"
                inside_link.symlink_to(inside_target)
                await assert_patch_failure_is_atomic(
                    session,
                    "workspace 내부 symbolic link 거부",
                    inside_target,
                    [{"old_text": "old", "new_text": "new"}],
                    snapshot_root,
                    path=relative_path(inside_link),
                )

                await assert_external_change_detected(
                    session=session,
                    workspace=workspace,
                    snapshot_root=snapshot_root,
                )
                await assert_snapshot_failure_is_atomic(
                    session=session,
                    workspace=workspace,
                    snapshot_root=snapshot_root,
                )
                assert temporary_patch_files(workspace) == []
                print("[PASS] 실패 후 임시 파일 정리")


if __name__ == "__main__":
    asyncio.run(main())
