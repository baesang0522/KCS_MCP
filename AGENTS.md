# AGENTS.md

## 프로젝트 목적
- 내부망 바이브코딩 시스템에서 사용할 MCP Tool Server다.
- 주요 사용자는 Supervisor / Planner / Coder 등의 LLM Agent다.
- 안전성, 예측 가능한 동작, 컨텍스트 효율성을 우선한다.
- Agent의 Tool 사용을 위해 꼼꼼하지만 길지 않게 Docstring 작성을 수행한다.

## 작업 원칙
- 복잡한 작업은 먼저 관련 파일을 확인하고 Plan을 작성한다.
- 한 번에 하나의 TODO만 처리한다.
- 요청과 관계없는 리팩터링이나 포맷 변경은 하지 않는다.
- 기존 구현을 확인하지 않고 구조를 추측해서 만들지 않는다.
- 코드 수정 후 `git diff`와 관련 테스트를 확인한다.

## Tool 설계 원칙
- Tool은 하나의 명확한 책임만 가진다.
- Agent가 판단하고 Tool은 가능한 한 deterministic하게 실행한다.
- Tool output은 구조화하고, 성공/실패를 명확히 구분한다.
- 큰 파일이나 검색 결과를 불필요하게 전체 반환하지 않는다.
- Tool docstring에는 목적, 입력, 출력, 실패 조건을 명확히 적는다.

## File Safety
- 모든 파일 접근은 workspace root 내부로 제한한다.
- path traversal과 symlink를 통한 workspace 탈출을 허용하지 않는다.
- 파일 수정 전 현재 내용을 확인한다.
- 전체 overwrite보다 `replace_text` 또는 patch 방식을 우선한다.
- destructive operation은 기본적으로 금지한다.

## Command Safety
- 명령 실행 시 cwd, timeout, exit code, stdout/stderr를 명확히 관리한다.
- `rm -rf`, `sudo`, `git reset --hard`, `git clean` 등 위험 명령은 사용자 승인 없이 실행하지 않는다.

## Python 환경
- dependency 관리는 `uv`를 사용한다.
- 패키지 추가: `uv add`
- 테스트: `uv run pytest`
- 직접 `pip install`은 특별한 이유가 없는 한 사용하지 않는다.

## 변경 시 주의
다음은 기존 Agent/Client와의 호환성에 영향을 줄 수 있으므로 임의로 변경하지 않는다.
- Tool name
- parameter schema
- return schema
- workspace/path validation 정책
- command 실행 정책

## 작업 완료 시
다음을 간단히 보고한다.
1. 변경한 내용
2. 변경 이유
3. 검증 결과
4. 남은 리스크