# 통합 업무 챗봇 (Python + FastAPI + Ollama + Qwen + RAG)

관리자가 매뉴얼을 업로드하면 임베딩을 생성하여 SQLite에 저장하고, 직원별 부서 접근권한에 맞는 문서에서만 검색하여 근거 기반 답변을 생성합니다. **OpenAI API 키는 필요 없습니다.**

## 1. 요구 환경
- Windows 10/11 또는 Linux, Python 3.11~3.13 권장
- Ollama 설치: https://ollama.com/download
- 개인 PC에서도 실행 가능. 동시 이용자가 많거나 대용량 매뉴얼이 많으면 전용 GPU 서버와 PostgreSQL/pgvector로 확장할 것을 권장합니다.

## 2. 모델 다운로드 (PowerShell 또는 터미널)
```powershell
ollama pull qwen3.5:4b
ollama pull qwen3-embedding:0.6b
ollama list
```
RAM/GPU 여유가 있으면 `ollama pull qwen3.5:9b` 후 `.env`의 `CHAT_MODEL=qwen3.5:9b`로 변경하세요. 강력한 GPU 서버라면 qwen3.6:27b 등 다른 Ollama 등록 모델도 설정할 수 있습니다.

## 3. Windows 실행
```powershell
cd company_rag_chatbot
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
`.env`에 `SESSION_SECRET`(최소 32자리 무작위 값)과 `ADMIN_PASSWORD`(10자리 이상 권장)를 반드시 입력하세요. 안전한 키 생성: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

PowerShell 가상환경 활성화가 막히면 활성화를 생략하고 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`, `.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000`처럼 실행합니다.

## 4. 접속 / 시연
1. 브라우저에서 http://127.0.0.1:8000
2. `.env`의 관리자 계정으로 로그인
3. 관리자 화면에서 `sample_docs/휴가_신청_매뉴얼.txt` 업로드 (전체 공개)
4. `휴가 신청 절차를 알려주세요` 질문
5. 관리자에서 직원 생성 → 직원으로 로그인하여 질문
6. 부서 전용 매뉴얼은 해당 부서 직원과 관리자만 검색할 수 있습니다.

## 5. 다른 직원 PC 접속 (시험망에서만)
서버에서 `--host 0.0.0.0`으로 실행하고 방화벽에서 서버 포트 8000을 허용한 다음 다른 PC에서 `http://서버_IP:8000`으로 접속할 수 있습니다. **이 방식은 암호화되지 않은 HTTP이므로 실제 회사 비밀번호나 민감 문서를 사용하면 안 됩니다.** 운영에서는 Nginx/Caddy HTTPS 프록시를 구성하고 `SESSION_HTTPS_ONLY=true`로 변경하세요. Ollama 11434 포트는 외부에 공개하지 마세요.

## 6. 파일 구조
```
main.py               로그인, 관리자, 대화 API, 권한검사
rag.py                문서 파싱, 청킹, 임베딩, 검색, 답변
config.py             환경변수
 db.py                SQLite 테이블, 감사 기록
 templates/           HTML 화면
 static/              CSS + 브라우저 JS
 sample_docs/         테스트용 문서
 data/chatbot.sqlite3 실행 시 자동 생성 (원본 문서 파일은 보관하지 않음)
```

## 7. 문서 처리 흐름
```
관리자 업로드 → 텍스트 추출 → 900자 청킹(150자 중첩)
→ Ollama /api/embed → SQLite 벡터 저장
직원 질문 → 질문 임베딩 → 부서 접근권한 필터 → 코사인 유사도 검색
→ 상위 5개 문서 발췌 → Ollama /api/chat → 답변 + 출처 → 직원별 대화 저장
```

### 주의 및 운영 이행 체크리스트
- **실제 기업 운영 전 보강 필요**: 회사 SSO(Microsoft Entra ID/LDAP 등) 연동, 로그인 실패 제한, HTTPS, 감사 로그 보관 정책, 개인정보 마스킹, 백업, 취약점 점검, 관리자 2FA, 계정 비밀번호 재설정, 파일 악성코드 검사, 보안 검토, 적절한 용량 계획.
- 이 예제는 부서 단위 ACL만 지원합니다. 비공개/인사/법무 문서는 더 세밀한 권한과 접근 감사가 필요합니다.
- SQLite 벡터 검색은 작은/중간 규모 실습용 선형 탐색입니다. 대용량은 PostgreSQL + pgvector/Qdrant 등으로 바꾸세요.
- 임베딩 모델을 변경했다면 기존 문서를 삭제하고 새 모델로 재업로드해야 합니다.
- 스캔 PDF, HWP/HWPX, XLSX, 이미지 문서는 직접 처리하지 않습니다. OCR/HWP 변환 파이프라인 추가가 필요합니다.
- 원본 파일은 저장하지 않고 추출 텍스트/벡터만 DB에 저장됩니다. **사내 문서 데이터는 DB에 그대로 남으므로 DB 백업과 접근 권한을 보호하세요.**
- 특정 자료에서 답변했다고 해도 모델이 틀릴 수 있으니 중요한 내용은 원문 대조가 필요합니다.
- 최초 관리자 계정은 DB가 없을 때만 생성됩니다. `.env`의 관리자 암호를 나중에 변경해도 기존 DB 암호는 자동 변경되지 않습니다. 로그인 후 '내 비밀번호 변경'에서 수정하세요.
- 현재 앱은 단일 서버 프로세스 테스트를 기준으로 합니다. 운영용 로드밸런싱, 속도제한, 작업큐, 감시 체계는 별도 구현하세요.
