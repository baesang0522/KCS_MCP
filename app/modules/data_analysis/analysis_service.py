from __future__ import annotations

from typing import Any

from app.utils.dataframe_utils import load_table_dataframe
from app.utils.statistics_utils import summarize_dataframe


def inspect_table(
    workspace_root: str,
    path: str,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """
    Parquet, XLSX, CSV 테이블의 구조와 컬럼 통계를 조회한다.

    실제 row나 샘플은 반환하지 않는다. 반환 크기는 행 수가 아닌
    컬럼 수에 비례한다.

    Args:
        workspace_root:
            파일 접근을 허용할 작업공간 루트 경로.

        path:
            workspace_root 기준 파일 경로.
            .parquet, .xlsx, .csv를 지원한다.

        sheet_name:
            XLSX 시트 이름. 생략하면 첫 번째 시트를 사용한다.
            Parquet과 CSV에는 지정할 수 없다.

    Returns:
        다음 형식의 dictionary를 반환한다.

        {
            "row_count": 100,
            "column_count": 2,
            "columns": [
                {
                    "name": "amount",
                    "dtype": "float64",
                    "null_count": 3,
                    "null_ratio": 0.03,
                    "n_unique": 72
                }
            ]
        }

        n_unique는 null을 제외한 고유값 개수다.
        빈 테이블의 null_ratio는 0.0이다.

    Raises:
        FileNotFoundError:
            workspace_root 또는 파일이 존재하지 않을 때 발생한다.

        NotADirectoryError:
            workspace_root가 디렉토리가 아닐 때 발생한다.

        IsADirectoryError:
            path가 파일이 아닌 디렉토리일 때 발생한다.

        PermissionError:
            workspace_root 바깥에 접근하려 할 때 발생한다.

        ValueError:
            파일 형식이나 sheet_name이 잘못됐을 때 발생한다.

    Agent 사용 지침:
        - 분석 전에 테이블 구조를 파악할 때 사용해라.
        - XLSX가 아닌 파일에는 sheet_name을 전달하지 마라.
    """
    dataframe = load_table_dataframe(
        workspace_root=workspace_root,
        path=path,
        sheet_name=sheet_name,
    )

    return summarize_dataframe(dataframe)
