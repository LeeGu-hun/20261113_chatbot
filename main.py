import json
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature
from pwdlib import PasswordHash
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from config import (ADMIN_PASSWORD, ADMIN_USERNAME, HTTPS_ONLY, MAX_UPLOAD_MB,
                    ROOT, SESSION_SECRET, CHAT_MODEL, EMBED_MODEL)
from db import audit, database, init_db
from rag import ModelError, SUPPORTED, answer_question, index_document, retrieve

hasher = PasswordHash.recommended()


@asynccontextmanager
async def lifespan(app):
    if len(SESSION_SECRET) < 32 or SESSION_SECRET.startswith('CHANGE_ME'):
        raise RuntimeError('먼저 .env 파일의 SESSION_SECRET을 변경하세요.')
    if not ADMIN_PASSWORD or ADMIN_PASSWORD.startswith('CHANGE_ME'):
        raise RuntimeError('먼저 .env 파일의 ADMIN_PASSWORD를 변경하세요.')
    init_db()
    with database() as db:
        if not db.execute('SELECT id FROM users WHERE role="admin" LIMIT 1').fetchone():
            db.execute('''INSERT INTO users(username,display_name,password_hash,department,role)
                          VALUES(?,?,?,?,?)''',
                       (ADMIN_USERNAME, '관리자', hasher.hash(ADMIN_PASSWORD), '관리', 'admin'))
            print(f'초기 관리자 생성: {ADMIN_USERNAME} (로그인 후 비밀번호를 변경하세요)')
    yield


app = FastAPI(title='기업용 사내 매뉴얼 챗봇', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET or 'not-for-production',
                   max_age=8 * 3600, same_site='lax', https_only=HTTPS_ONLY)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
templates = Jinja2Templates(directory=ROOT / 'templates')


def me(request, db):
    uid = request.session.get('uid')
    if not uid:
        return None
    return db.execute('SELECT id,username,display_name,department,role,active FROM users WHERE id=? AND active=1',
                      (uid,)).fetchone()


def require_user(request, db):
    user = me(request, db)
    if not user:
        raise HTTPException(401, '로그인이 필요합니다.')
    return user


def require_admin(request, db):
    user = require_user(request, db)
    if user['role'] != 'admin':
        raise HTTPException(403, '관리자만 가능합니다.')
    return user


def verify_csrf(request, token):
    known = request.session.get('csrf', '')
    if not token or not known or not secrets.compare_digest(known, token):
        raise HTTPException(403, '보안 토큰이 올바르지 않습니다. 새로고침 후 다시 시도하세요.')


def render(request, template, **context):
    if 'csrf' not in request.session:
        request.session['csrf'] = secrets.token_urlsafe(32)
    return templates.TemplateResponse(request, template, {'request': request, 'csrf': request.session['csrf'], **context})


def message_error(request, message, code=400):
    return render(request, 'message.html', message=message, status_code=code)


@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    with database() as db:
        user = me(request, db)
        if not user:
            return RedirectResponse('/login', 303)
        conversations = db.execute('''SELECT id,title,created_at FROM conversations WHERE user_id=?
                                      ORDER BY id DESC LIMIT 40''', (user['id'],)).fetchall()
        return render(request, 'index.html', user=user, conversations=conversations,
                      chat_model=CHAT_MODEL, embed_model=EMBED_MODEL)


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, 'login.html', error='')


@app.post('/login')
def login(request: Request, username: str = Form(...), password: str = Form(...),
          csrf: str = Form(...)):
    verify_csrf(request, csrf)
    with database() as db:
        row = db.execute('SELECT * FROM users WHERE username=?', (username.strip(),)).fetchone()
        if not row or not row['active'] or not hasher.verify(password, row['password_hash']):
            audit(db, None, 'failed_login', username)
            return render(request, 'login.html', error='아이디 또는 비밀번호가 올바르지 않습니다.')
        request.session.clear()
        request.session['uid'] = row['id']
        request.session['csrf'] = secrets.token_urlsafe(32)
        audit(db, row['id'], 'login')
    return RedirectResponse('/', 303)


@app.post('/logout')
def logout(request: Request, csrf: str = Form(...)):
    verify_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse('/login', 303)


@app.get('/admin', response_class=HTMLResponse)
def admin_page(request: Request):
    with database() as db:
        user = require_admin(request, db)
        users = db.execute('SELECT id,username,display_name,department,role,active FROM users ORDER BY id').fetchall()
        docs = db.execute('''SELECT d.id,d.filename,d.department,d.chunk_count,d.created_at,u.display_name uploader
                             FROM documents d JOIN users u ON u.id=d.uploaded_by ORDER BY d.id DESC''').fetchall()
        return render(request, 'admin.html', user=user, users=users, docs=docs)


@app.post('/admin/users')
def create_user(request: Request, username: str = Form(...), display_name: str = Form(...),
                password: str = Form(...), department: str = Form(...),
                role: str = Form('employee'), csrf: str = Form(...)):
    verify_csrf(request, csrf)
    with database() as db:
        admin = require_admin(request, db)
        username, display_name, department = username.strip(), display_name.strip(), department.strip()
        if not 3 <= len(username) <= 40 or not username.replace('_','').isalnum():
            return message_error(request, '아이디는 영문/숫자/밑줄 등 3~40자로 작성하세요.')
        if not display_name or not department or len(password) < 10:
            return message_error(request, '이름/부서를 입력하고 비밀번호는 10자 이상으로 설정하세요.')
        if role not in ('employee','admin'):
            return message_error(request, '역할이 올바르지 않습니다.')
        if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
            return message_error(request, '이미 존재하는 아이디입니다.')
        db.execute('INSERT INTO users(username,display_name,password_hash,department,role) VALUES(?,?,?,?,?)',
                   (username, display_name, hasher.hash(password), department, role))
        audit(db, admin['id'], 'create_user', username)
    return RedirectResponse('/admin', 303)


@app.post('/admin/users/{user_id}/toggle')
def toggle_user(user_id: int, request: Request, csrf: str = Form(...)):
    verify_csrf(request, csrf)
    with database() as db:
        admin = require_admin(request, db)
        if user_id == admin['id']:
            return message_error(request, '본인의 계정은 비활성화할 수 없습니다.')
        target = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, '사용자를 찾을 수 없습니다.')
        if target['role'] == 'admin' and target['active'] and db.execute(
                "SELECT count(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
            return message_error(request, '마지막 관리자는 비활성화할 수 없습니다.')
        db.execute('UPDATE users SET active=? WHERE id=?', (0 if target['active'] else 1, user_id))
        audit(db, admin['id'], 'toggle_user', target['username'])
    return RedirectResponse('/admin', 303)


@app.post('/password')
def change_password(request: Request, current: str = Form(...), new_password: str = Form(...),
                    csrf: str = Form(...)):
    verify_csrf(request, csrf)
    with database() as db:
        user = require_user(request, db)
        row = db.execute('SELECT password_hash FROM users WHERE id=?', (user['id'],)).fetchone()
        if not hasher.verify(current, row['password_hash']) or len(new_password) < 10:
            return message_error(request, '현재 비밀번호가 틀렸거나 새 비밀번호가 10자 미만입니다.')
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (hasher.hash(new_password), user['id']))
        audit(db, user['id'], 'change_password')
    return RedirectResponse('/', 303)


@app.post('/admin/upload')
async def upload(request: Request, file: UploadFile = File(...), department: str = Form(''),
                 csrf: str = Form(...)):
    verify_csrf(request, csrf)
    with database() as db:
        admin = require_admin(request, db)
        filename = (file.filename or '').replace('\\', '/').split('/')[-1].strip()
        if not filename or len(filename) > 180 or '.' + filename.rsplit('.', 1)[-1].lower() not in SUPPORTED:
            return message_error(request, '지원 형식은 PDF, DOCX, TXT, MD입니다.')
        raw = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
            return message_error(request, f'파일 크기는 {MAX_UPLOAD_MB}MB 이하로 제한됩니다.')
        try:
            doc_id, count = index_document(db, filename, department.strip() or None, admin['id'], raw)
            audit(db, admin['id'], 'upload_document', f'{doc_id}: {filename} ({count} chunks)')
        except (ValueError, ModelError) as exc:
            return message_error(request, str(exc), 400)
    return RedirectResponse('/admin', 303)


@app.post('/admin/documents/{doc_id}/delete')
def delete_doc(doc_id: int, request: Request, csrf: str = Form(...)):
    verify_csrf(request, csrf)
    with database() as db:
        admin = require_admin(request, db)
        db.execute('DELETE FROM documents WHERE id=?', (doc_id,))
        audit(db, admin['id'], 'delete_document', doc_id)
    return RedirectResponse('/admin', 303)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: int | None = None
    csrf: str


@app.post('/api/chat')
def chat(request: Request, body: ChatRequest):
    verify_csrf(request, body.csrf)
    with database() as db:
        user = require_user(request, db)
        if body.conversation_id is not None:
            conversation = db.execute('SELECT id FROM conversations WHERE id=? AND user_id=?',
                                      (body.conversation_id, user['id'])).fetchone()
            if not conversation:
                raise HTTPException(404, '대화를 찾을 수 없습니다.')
            conversation_id = conversation['id']
        else:
            conversation_id = None
        history = []
        if conversation_id:
            rows = db.execute('''SELECT role,content FROM messages WHERE conversation_id=?
                                 ORDER BY id DESC LIMIT 6''', (conversation_id,)).fetchall()
            history = [dict(row) for row in reversed(rows)]
        try:
            sources = retrieve(db, body.question, user['department'], user['role'] == 'admin')
            reply = answer_question(body.question, sources, history)
        except ModelError as exc:
            raise HTTPException(503, str(exc)) from exc
        if conversation_id is None:
            cur = db.execute('INSERT INTO conversations(user_id,title) VALUES(?,?)',
                             (user['id'], body.question[:70]))
            conversation_id = cur.lastrowid
        db.execute("INSERT INTO messages(conversation_id,role,content) VALUES(?,'user',?)",
                   (conversation_id, body.question))
        public_sources = [{k: s[k] for k in ('filename','part','score','text')}
                          for s in sources]
        db.execute('''INSERT INTO messages(conversation_id,role,content,sources_json)
                      VALUES(?,'assistant',?,?)''',
                   (conversation_id, reply, json.dumps(public_sources, ensure_ascii=False)))
        audit(db, user['id'], 'chat', f'conversation={conversation_id}')
        return {'conversation_id': conversation_id, 'answer': reply, 'sources': public_sources}


@app.get('/api/conversations/{conversation_id}')
def read_conversation(conversation_id: int, request: Request):
    with database() as db:
        user = require_user(request, db)
        conv = db.execute('SELECT id,title FROM conversations WHERE id=? AND user_id=?',
                          (conversation_id, user['id'])).fetchone()
        if not conv:
            raise HTTPException(404, '대화를 찾을 수 없습니다.')
        messages = db.execute('SELECT role,content,sources_json FROM messages WHERE conversation_id=? ORDER BY id',
                              (conversation_id,)).fetchall()
        return {'id': conv['id'], 'title': conv['title'], 'messages': [
            {'role': m['role'], 'content': m['content'], 'sources': json.loads(m['sources_json'])}
            for m in messages]}


@app.get('/health')
def health():
    return {'ok': True, 'chat_model': CHAT_MODEL, 'embed_model': EMBED_MODEL}
