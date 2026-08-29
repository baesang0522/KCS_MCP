from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.utils.excel_utils import read_excel_dataframe


SUPPORTED_TABLE_SUFFIXES = {
    ".parquet",
    ".xlsx",
    ".csv",
}


def _resolve_table_path(
    workspace_root: str,
    path: str,
) -> Path:
    """
    workspace 내부의 테이블 경로를 안전한 절대 경로로 변환한다.

    Args:
        workspace_root:
            파일 접근을 허용할 작업공간 루트 경로.

        path:
            workspace_root 기준 파일 경로.

    Returns:
        검증한 파일의 절대 Path를 반환한다.

    Raises:
        FileNotFoundError:
            workspace_root 또는 파일이 없을 때 발생한다.

        NotADirectoryError:
            workspace_root가 디렉토리가 아닐 때 발생한다.

        IsADirectoryError:
            path가 디렉토리일 때 발생한다.

        PermissionError:
            파일이 workspace_root 바깥을 가리킬 때 발생한다.
    """
    root = Path(workspace_root).expanduser().resolve()

    if not root.exists():
        raise FileNotFoundError(
            f"workspace_root가 존재하지 않습니다: {workspace_root}"
        )

    if not root.is_dir():
        raise NotADirectoryError(
            f"workspace_root가 디렉토리가 아닙니다: {workspace_root}"
        )

    target = (root / path).resolve()

    if target != root and root not in target.parents:
        raise PermissionError(
            f"작업공간 외부 파일에는 접근할 수 없습니다: {path}"
        )

    if not target.exists():
        raise FileNotFoundError(
            f"파일이 존재하지 않습니다: {path}"
        )

    if not target.is_file():
        raise IsADirectoryError(
            f"파일이 아닙니다: {path}"
        )

    return target


def load_table_dataframe(
    workspace_root: str,
    path: str,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    """
    지원하는 테이블 파일을 검증하고 pandas DataFrame으로 읽는다.

    Args:
        workspace_root:
            파일 접근을 허용할 작업공간 루트 경로.

        path:
            workspace_root 기준 파일 경로.
            .parquet, .xlsx, .csv를 지원한다.

        sheet_name:
            XLSX 시트 이름. 다른 형식에는 지정할 수 없다.

    Returns:
        파일을 읽은 pandas DataFrame을 반환한다.

    Raises:
        ValueError:
            확장자가 잘못됐거나 XLSX가 아닌 파일에 sheet_name을
            지정했을 때 발생한다.

        FileNotFoundError:
            workspace_root 또는 파일이 없을 때 발생한다.

        PermissionError:
            workspace_root 바깥에 접근하려 할 때 발생한다.
    """
    target = _resolve_table_path(
        workspace_root=workspace_root,
        path=path,
    )
    suffix = target.suffix.lower()

    if suffix not in SUPPORTED_TABLE_SUFFIXES:
        supported = ", ".join(
            sorted(SUPPORTED_TABLE_SUFFIXES)
        )
        raise ValueError(
            f"지원하지 않는 파일 형식입니다: {suffix or '(확장자 없음)'} "
            f"(지원 형식: {supported})"
        )

    if suffix != ".xlsx" and sheet_name is not None:
        raise ValueError(
            "sheet_name은 XLSX 파일에서만 사용할 수 있습니다."
        )

    if suffix == ".parquet":
        return pd.read_parquet(
            target,
            engine="pyarrow",
        )

    if suffix == ".csv":
        return pd.read_csv(
            target,
            low_memory=False,
        )

    return read_excel_dataframe(
        path=target,
        sheet_name=sheet_name,
    )
