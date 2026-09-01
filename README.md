# KCS_MCP
MCP SERVER

1. brew 설치   
2. uv 설치 
3. clone
4. $ uv sync  
5. ollama 설치(macOS 14 sonoma 이상 필요)
> 차례대로 터미널에서  
> ollama 설치
>> brew install ollama
> 
> ollama 띄우기
>> ollama serve
>
> gemma4 최소모델 설치(새 터미널에서)
>> ollama pull gemma4:e2b
> 
> 실행
>> ollama run gemma4:e2b
> 
> 서빙 확인
>> curl http://localhost:11434/api/tags
> 
> 중지
>> brew services stop ollama
> 
> 실행
>> brew services start ollama
  

6. 테스트 방법
> mcp server local에서 열기
>> uvicorn app.main:app --host 0.0.0.0 --port 8443
> 
이후 테스트 폴더 안에 테스트 코드 만들어놓고 실행  

| 구분 | Excel/VBA 방식 | Streamlit + Python 방식 |
|---|---|---|
| 대용량 데이터 처리 | 사용자 PC 메모리/CPU 의존 | **서버 자원 사용** |
| 사용자 PC 영향 | 데이터가 커질수록 Excel 무거워짐 | **브라우저만 사용** |
| 환경 편차 | PC 사양별 차이 | **서버 기준으로 일관됨** |
| 분석 기능 확장 | VBA/Excel 기능에 제한 | **Python 분석 생태계 활용** |
| LLM 대량 처리 | 구현 가능하지만 복잡 | **batch/async/cache 구현 용이** |
| 유지보수 | 매크로 파일별 관리 가능성 | **서버 한 곳에서 관리** |
| 버전 배포 | 사용자 파일 갱신 필요 | **웹 서비스 즉시 반영** |
| 보안 관리 | API 설정이 클라이언트에 존재 가능 | **서버 내부 집중 관리** |