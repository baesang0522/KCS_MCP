# 보안상 agent가 아닌 harness가 workspace_root를 제공함
import codecs
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from app.modules.code_setup.investigation_service import (
    DEFAULT_IGNORE_DIRS,
    _resolve_path,
)


MAX_WRITE_CHARS = 1_000_000
ALLOWED_CONTROL_CHARACTERS = "\t\n\r\f"


def _contains_disallowed_control_character(
    content: str,
) -> bool:
    """텍스트에 허용하지 않는 제어문자가 있는지 확인한다."""
    return any(
        (
            ord(character) < 32
            and character not in ALLOWED_CONTROL_CHARACTERS
        )
        or ord(character) == 127
        for character in content
    )


def _validate_existing_text_file(path: Path) -> None:
    """기존 파일이 UTF-8 텍스트 파일인지 전체 내용을 확인한다."""
    decoder = codecs.getincrementaldecoder("utf-8")(
        errors="strict"
    )

    try:
        with path.open(mode="rb") as file:
            while chunk := file.read(8192):
                content = decoder.decode(chunk)

                if _contains_disallowed_control_character(
                    content
                ):
                    raise ValueError(
                        "binary 파일은 덮어쓸 수 없습니다."
                    )

            remaining_content = decoder.decode(
                b"",
                final=True,
            )

            if _contains_disallowed_control_character(
                remaining_content
            ):
                raise ValueError(
                    "binary 파일은 덮어쓸 수 없습니다."
                )
    except UnicodeDecodeError as exc:
        raise ValueError(
            "비 UTF-8 파일은 덮어쓸 수 없습니다."
        ) from exc


def _resolve_write_path(
    workspace_root: str,
    path: str,
) -> tuple[Path, Path, str]:
    """새 파일도 처리할 수 있도록 안전한 workspace 쓰기 경로를 만든다."""
    if not path or not path.strip():
        raise ValueError(
            "path는 비어 있을 수 없습니다."
        )

    relative_path = Path(path)

    if relative_path.is_absolute():
        raise PermissionError(
            "절대경로에는 파일을 쓸 수 없습니다."
        )

    if relative_path == Path("."):
        raise IsADirectoryError(
            "workspace_root에는 파일을 쓸 수 없습니다."
        )

    if ".." in relative_path.parts:
        raise PermissionError(
            "'..'이 포함된 경로에는 파일을 쓸 수 없습니다."
        )

    protected_directory = next(
        (
            part
            for part in relative_path.parts
            if part in DEFAULT_IGNORE_DIRS
        ),
        None,
    )

    if protected_directory is not None:
        raise PermissionError(
            "보호된 디렉토리에는 파일을 쓸 수 없습니다: "
            f"{protected_directory}"
        )

    root, _ = _resolve_path(
        workspace_root=workspace_root,
        path=".",
    )
    unresolved_target = root / relative_path
    target = unresolved_target.resolve(strict=False)

    if target != root and root not in target.parents:
        raise PermissionError(
            "작업공간 외부 경로에는 파일을 쓸 수 없습니다: "
            f"{path}"
        )

    current_path = root

    for part in relative_path.parts:
        if part in {"", "."}:
            continue

        current_path /= part

        if current_path.is_symlink():
            raise PermissionError(
                "symbolic link 경로에는 파일을 쓸 수 없습니다: "
                f"{path}"
            )

    normalized_path = target.relative_to(root).as_posix()

    return root, target, normalized_path


def _write_atomically(
    target: Path,
    content: bytes,
    existing_mode: int | None,
) -> None:
    """같은 디렉토리의 임시 파일을 이용해 내용을 원자적으로 기록한다."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(descriptor, mode="wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.chmod(
            temporary_path,
            existing_mode
            if existing_mode is not None
            else 0o644,
        )

        if existing_mode is None:
            os.link(temporary_path, target)
        else:
            os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_file(
    workspace_root: str,
    path: str,
    content: str,
    overwrite: bool = False,
    create_parent_dirs: bool = False,
) -> dict[str, Any]:
    """
    workspace 내부에 UTF-8 텍스트 파일을 새로 만들거나 전체 교체한다.

    기존 파일 전체 교체에는 overwrite=True가 필요하다. 부분 수정에는
    사용하지 않으며 입력받은 content를 개행 변환 없이 그대로 기록한다.

    Args:
        workspace_root:
            파일 쓰기를 허용할 작업공간 루트 경로. 모든 쓰기는 이 경로
            내부로 제한한다. 예: "/workspace/project"

        path:
            생성하거나 전체 교체할 파일의 workspace_root 기준 상대경로.
            절대경로, '..', symbolic link 경로는 허용하지 않는다.
            예: "src/services/user_service.py"

        content:
            파일에 기록할 전체 문자열. UTF-8로 인코딩하며 개행 문자를
            포함한 입력 내용을 그대로 기록한다. 최대 1,000,000자까지
            허용한다.

        overwrite:
            기존 파일 전체를 교체할지 여부. 기본값은 False다.
            False인데 대상 파일이 이미 존재하면 FileExistsError가 발생한다.

        create_parent_dirs:
            존재하지 않는 부모 디렉토리를 함께 만들지 여부.
            기본값은 False다. False인데 부모가 없으면 FileNotFoundError가
            발생한다.

    Returns:
        {
            "path": "src/services/user_service.py",
            "operation": "created",
            "chars_written": 120,
            "bytes_written": 128
        }

        operation은 created, overwritten, unchanged 중 하나다. 실제로 기록한
        문자 수와 UTF-8 byte 수만 반환하고 파일 내용은 반환하지 않는다.

    Raises:
        FileNotFoundError:
            workspace_root가 존재하지 않거나 create_parent_dirs가 False인
            상태에서 부모 디렉토리가 존재하지 않을 때 발생한다.

        FileExistsError:
            overwrite가 False인데 대상 파일이 이미 존재할 때 발생한다.

        IsADirectoryError:
            path가 파일이 아닌 디렉토리를 가리킬 때 발생한다.

        NotADirectoryError:
            workspace_root가 디렉토리가 아닐 때 발생한다.

        PermissionError:
            workspace 외부, 절대경로, '..', symbolic link, 보호된 디렉토리에
            쓰려고 하거나 파일 쓰기 권한이 없을 때 발생한다.

        ValueError:
            path가 비었거나 content가 제한을 초과하거나 제어문자를 포함하거나,
            .ipynb, binary, 비 UTF-8 파일을 처리하려 할 때 발생한다.

        OSError:
            디렉토리 또는 파일을 생성하거나 원자적으로 교체하지 못했을 때
            발생한다.

    Agent 사용 지침:
        - 새 파일을 만들거나 기존 파일 전체를 다시 작성할 때만 사용해라.
        - 기존 파일을 교체하기 전에 read_file로 현재 내용을 확인해라.
        - 기존 파일을 교체할 때만 overwrite=True를 전달해라.
        - 일부 코드만 바꾸려면 부분 수정 전용 Tool을 사용해라.
        - 부모 디렉토리도 새로 만들어야 할 때만 create_parent_dirs=True를
          전달해라.
    """
    if not isinstance(content, str):
        raise TypeError(
            "content는 문자열이어야 합니다."
        )

    if len(content) > MAX_WRITE_CHARS:
        raise ValueError(
            "content는 최대 "
            f"{MAX_WRITE_CHARS:,}자까지 쓸 수 있습니다."
        )

    if _contains_disallowed_control_character(content):
        raise ValueError(
            "content에 허용되지 않는 제어문자가 포함되어 있습니다."
        )

    try:
        encoded_content = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "content를 UTF-8로 인코딩할 수 없습니다."
        ) from exc

    _, target, normalized_path = _resolve_write_path(
        workspace_root=workspace_root,
        path=path,
    )

    if target.suffix.lower() == ".ipynb":
        raise ValueError(
            ".ipynb 파일은 write_file로 쓸 수 없습니다."
        )

    if target.exists() and target.is_dir():
        raise IsADirectoryError(
            f"파일 대신 디렉토리가 지정되었습니다: {path}"
        )

    parent = target.parent

    if parent.exists() and not parent.is_dir():
        raise NotADirectoryError(
            f"부모 경로가 디렉토리가 아닙니다: {path}"
        )

    if not parent.exists():
        if not create_parent_dirs:
            raise FileNotFoundError(
                f"부모 디렉토리가 존재하지 않습니다: {path}"
            )

        try:
            parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        except PermissionError as exc:
            raise PermissionError(
                f"부모 디렉토리를 만들 권한이 없습니다: {path}"
            ) from exc

    try:
        if parent.resolve(strict=True) != parent:
            raise PermissionError(
                "symbolic link 부모 경로에는 파일을 쓸 수 없습니다: "
                f"{path}"
            )
    except RuntimeError as exc:
        raise PermissionError(
            f"안전하지 않은 부모 경로에는 파일을 쓸 수 없습니다: {path}"
        ) from exc

    if target.is_symlink():
        raise PermissionError(
            "symbolic link 경로에는 파일을 쓸 수 없습니다: "
            f"{path}"
        )

    target_exists = target.exists()
    existing_mode: int | None = None

    if target_exists:
        if not target.is_file():
            raise ValueError(
                f"일반 텍스트 파일만 덮어쓸 수 있습니다: {path}"
            )

        if not overwrite:
            raise FileExistsError(
                f"파일이 이미 존재합니다: {normalized_path}"
            )

        _validate_existing_text_file(target)
        existing_mode = stat.S_IMODE(
            target.stat().st_mode
        )

        if (
            target.stat().st_size == len(encoded_content)
            and target.read_bytes() == encoded_content
        ):
            return {
                "path": normalized_path,
                "operation": "unchanged",
                "chars_written": 0,
                "bytes_written": 0,
            }

    try:
        _write_atomically(
            target=target,
            content=encoded_content,
            existing_mode=existing_mode,
        )
    except PermissionError as exc:
        raise PermissionError(
            f"파일을 쓸 권한이 없습니다: {normalized_path}"
        ) from exc

    return {
        "path": normalized_path,
        "operation": (
            "overwritten"
            if target_exists
            else "created"
        ),
        "chars_written": len(content),
        "bytes_written": len(encoded_content),
    }
