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