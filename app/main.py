from pathlib import Path

# 표준 라이브러리
from datetime import datetime

# CORS
from fastapi.middleware.cors import CORSMiddleware

# MCP 2.x
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

# 기존 서비스 import
# from modules.bdp_project.bdp_service import (
#     get_current_datetime,
#     predict_hs_code,
# )
#
# from modules.customs_administration.law_service import (
#     search_law_by_hierarchy,
#     search_laws_by_topic,
# )
#
# from modules.artifact.artifact_service import (
#     search_artifacts_by_project,
#     search_artifacts_comprehensive,
#     search_artifacts_by_keywords,
#     search_artifacts_by_page_range,
#     get_document_by_filename,
#     list_available_projects,
# )
#
# from modules.database.meta_service import (
#     search_table_metadata,
#     get_table_relationships,
#     get_semantic_code_mapping,
# )

# from modules.database.database_service import query_database

from app.modules.code_setup.investigation_service import (
    list_files,
    read_file,
    search_code,
    get_project_tree,
)
from app.modules.code_edit.code_edit import (
    apply_patch,
    write_file,
)
from app.modules.code_edit.jupyter_code_edit import (
    write_jupyter_code_cell,
)
from app.modules.data_analysis.analysis_service import (
    inspect_table,
    preview_rows,
)

# ---------------------------------------------------------
# MCP transport security
# ---------------------------------------------------------

security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,

    allowed_hosts=[
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",

        "anlapi.customs.go.kr",
        "anlapi.customs.go.kr:*",
        "anlapi.customs.go.kr:8443",
    ],

    allowed_origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",

        "https://anlapi.customs.go.kr",
        "https://anlapi.customs.go.kr:*",
        "https://anlapi.customs.go.kr:8443",
    ],
)


# ---------------------------------------------------------
# MCP Server
# ---------------------------------------------------------

mcp = MCPServer(
    name="BDP MCP Server",
)


# ---------------------------------------------------------
# 기본 Tool 등록
# ---------------------------------------------------------

# mcp.tool()(get_current_datetime)
# mcp.tool()(predict_hs_code)
#
#
# # ---------------------------------------------------------
# # 법령 Tool 등록
# # ---------------------------------------------------------
#
# mcp.tool()(search_law_by_hierarchy)
# mcp.tool()(search_laws_by_topic)
#
#
# # ---------------------------------------------------------
# # 산출물 Tool 등록
# # ---------------------------------------------------------
#
# mcp.tool()(search_artifacts_by_project)
# mcp.tool()(search_artifacts_comprehensive)
# mcp.tool()(search_artifacts_by_keywords)
# mcp.tool()(search_artifacts_by_page_range)
# mcp.tool()(get_document_by_filename)
# mcp.tool()(list_available_projects)
#
#
# # ---------------------------------------------------------
# # 메타 / NULL Tool 등록
# # ---------------------------------------------------------
#
# mcp.tool()(search_table_metadata)
# mcp.tool()(get_table_relationships)
# mcp.tool()(get_semantic_code_mapping)
#
#
# # ---------------------------------------------------------
# # DB 조회 Tool 등록
# # ---------------------------------------------------------
#
# mcp.tool()(query_database)

# ---------------------------------------------------------
# 파일 조회 Tool 등록
# ---------------------------------------------------------
mcp.tool()(list_files)
mcp.tool()(read_file)
mcp.tool()(search_code)
mcp.tool()(get_project_tree)

# ---------------------------------------------------------
# 코드 수정 Tool 등록
# ---------------------------------------------------------
mcp.tool()(write_file)
mcp.tool()(apply_patch)
mcp.tool()(write_jupyter_code_cell)

# ---------------------------------------------------------
# 데이터 분석 Tool 등록
# ---------------------------------------------------------
mcp.tool()(inspect_table)
mcp.tool()(preview_rows)

# ---------------------------------------------------------
# Streamable HTTP ASGI App
# ---------------------------------------------------------

app = mcp.streamable_http_app(
    transport_security=security,
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,

    allow_origins=[
        "https://anlapi.customs.go.kr",
        "https://anlapi.customs.go.kr:8443",
    ],

    allow_credentials=True,

    allow_methods=[
        "GET",
        "POST",
        "DELETE",
        "OPTIONS",
    ],

    allow_headers=[
        "Authorization",
        "Content-Type",
        "Last-Event-ID",
        "Mcp-Method",
        "Mcp-Name",
        "Mcp-Protocol-Version",
        "Mcp-Session-Id",
    ],

    expose_headers=[
        "Mcp-Session-Id",
    ],
)
