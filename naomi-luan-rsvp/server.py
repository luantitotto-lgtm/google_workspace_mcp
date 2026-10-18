"""Naomi & Luan — RSVP, persistence and organizer area.

Run: ADMIN_PASSWORD='...' SESSION_SECRET='...' uvicorn server:app --reload
"""
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import psycopg
from psycopg.rows import dict_row
import time
import unicodedata
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
# Real RSVPs require persistent PostgreSQL on Render. SQLite is only for local testing.
DATABASE_URL = os.environ.get('DATABASE_URL', '')
IS_RENDER = bool(os.environ.get('RENDER'))
DATA_DIR = Path(os.environ.get('DATA_DIR', ROOT / 'data'))
if not IS_RENDER and not DATABASE_URL:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / 'rsvp.db'

class PgAdapter:
    def __init__(self):
        self.db = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8)
    def __enter__(self):
        self.db.__enter__()
        return self
    def __exit__(self, *args):
        return self.db.__exit__(*args)
    def execute(self, query, params=()):
        return self.db.execute(query.replace('?', '%s'), params)

SECRET = os.environ.get('SESSION_SECRET', '')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'false').lower() == 'true'
app = FastAPI(title='Naomi & Luan RSVP', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')

class RSVP(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(default='', max_length=255)
    phone: str = Field(default='', max_length=35)
    attendance: Literal['yes', 'no']
    guest_names: list[str] = Field(default_factory=list, max_length=5)
    dietary: str = Field(default='', max_length=500)
    note: str = Field(default='', max_length=1000)
    privacy_consent: bool
    website: str = ''

def conn():
    if DATABASE_URL:
        return PgAdapter()
    if IS_RENDER:
        raise HTTPException(503, 'O RSVP está em configuração. Banco de dados ainda não conectado.')
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db

def init():
    if DATABASE_URL:
        with conn() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rsvps (
                id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT, phone TEXT,
                attendance TEXT NOT NULL CHECK (attendance IN ('yes', 'no')),
                guest_names TEXT NOT NULL, dietary TEXT, note TEXT,
                token_hash TEXT NOT NULL UNIQUE,
                created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id BIGSERIAL PRIMARY KEY, ip_hash TEXT NOT NULL, action TEXT NOT NULL, ts BIGINT NOT NULL)""")
            db.execute('CREATE INDEX IF NOT EXISTS attempts_ix ON attempts(ip_hash, action, ts)')
            db.execute('CREATE INDEX IF NOT EXISTS rsvps_token_ix ON rsvps(token_hash)')
        return
    if IS_RENDER:
        return
    with conn() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS rsvps (
                id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT, phone TEXT,
                attendance TEXT NOT NULL CHECK(attendance IN ('yes','no')),
                guest_names TEXT NOT NULL, dietary TEXT, note TEXT,
                token_hash TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, ip_hash TEXT NOT NULL, action TEXT NOT NULL, ts INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS attempts_ix ON attempts(ip_hash, action, ts);
            CREATE INDEX IF NOT EXISTS rsvps_token_ix ON rsvps(token_hash);
        ''')
try:
    init()
except psycopg.Error:
    # Website can boot while Postgres finishes provisioning; write endpoints remain unavailable.
    pass

@app.get('/api/status')
def status():
    if not DATABASE_URL:
        return {'ready': not IS_RENDER, 'database': 'not_configured' if IS_RENDER else 'local_testing'}
    try:
        with conn() as db:
            db.execute('SELECT 1')
        return {'ready': True, 'database': 'postgres'}
    except Exception:
        return {'ready': False, 'database': 'temporarily_unavailable'}

def canonical(v):
    return unicodedata.normalize('NFKC', v or '').strip()

def clean(p: RSVP):
    if not p.privacy_consent:
        raise HTTPException(422, 'É necessário aceitar o aviso de privacidade.')
    if p.website:
        raise HTTPException(400, 'Solicitação não aceita.')
    p.full_name = ' '.join(canonical(p.full_name).split())
    if len(p.full_name) < 2:
        raise HTTPException(422, 'Informe seu nome completo.')
    p.email = canonical(p.email).lower()
    p.phone = canonical(p.phone)
    p.dietary = canonical(p.dietary)
    p.note = canonical(p.note)
    if p.email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', p.email):
        raise HTTPException(422, 'O e-mail informado não é válido.')
    if p.phone and len(re.sub(r'\D','',p.phone)) < 8:
        raise HTTPException(422, 'Confira o número de telefone.')
    p.guest_names = [' '.join(canonical(n).split()) for n in p.guest_names]
    if p.attendance == 'no':
        p.guest_names = []
        p.dietary = ''
    elif any(not n or len(n) > 100 for n in p.guest_names):
        raise HTTPException(422, 'Preencha o nome de cada acompanhante.')
    return p

def digest(v):
    # For edits the random private token is already high-entropy; SHA-256 stores only its digest.
    return hashlib.sha256(v.encode()).hexdigest()

def ip_key(request: Request):
    # Server sees a peer address; avoids trusting unvalidated X-Forwarded-For headers.
    ip = request.client.host if request.client else 'unknown'
    return hmac.new((SECRET or 'local-rate-limit').encode(), ip.encode(), hashlib.sha256).hexdigest()

def rate_limit(request: Request, action: str, max_count: int, window: int):
    now = int(time.time())
    key = ip_key(request)
    with conn() as db:
        db.execute('DELETE FROM attempts WHERE ts < ?', (now - 86400,))
        count = db.execute('SELECT count(*) AS n FROM attempts WHERE ip_hash=? AND action=? AND ts>=?', (key, action, now-window)).fetchone()['n']
        if count >= max_count:
            raise HTTPException(429, 'Muitas tentativas. Aguarde um pouco para tentar novamente.')
        db.execute('INSERT INTO attempts(ip_hash,action,ts) VALUES(?,?,?)', (key,action,now))

def same_origin(request: Request):
    origin = request.headers.get('origin')
    if origin:
        expected = str(request.base_url).rstrip('/')
        # On TLS proxies, supplied origin must match host; no cross-site writes.
        if origin.split('://')[-1].rstrip('/') != expected.split('://')[-1].rstrip('/'):
            raise HTTPException(403, 'Origem não permitida.')

def receipt(row):
    return {
        'full_name': row['full_name'], 'attendance': row['attendance'],
        'guest_names': json.loads(row['guest_names']), 'email': row['email'] or '',
        'phone': row['phone'] or '', 'dietary': row['dietary'] or '', 'note': row['note'] or '',
        'updated_at': row['updated_at'], 'protocol': row['id'][:8].upper()
    }

@app.get('/', include_in_schema=False)
def homepage():
    return FileResponse(ROOT / 'static' / 'index.html')

@app.post('/api/rsvp')
def save(request: Request, p: RSVP):
    same_origin(request)
    if DATABASE_URL:
        init()
    rate_limit(request, 'rsvp', 12, 3600)
    p = clean(p)
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    rid = secrets.token_hex(16)
    with conn() as db:
        # Retry after accidental double clicks must not create duplicate records.
        exists = db.execute('''SELECT id FROM rsvps WHERE lower(full_name)=lower(?)
            AND ((email != '' AND email=?) OR (phone != '' AND phone=?) OR lower(full_name)=lower(?)) AND updated_at>? LIMIT 1''',
            (p.full_name, p.email, p.phone, p.full_name, now - 900)).fetchone()
        if exists:
            raise HTTPException(409, 'Já recebemos uma resposta recente com esses dados. Use seu link privado para alterá-la.')
        db.execute('''INSERT INTO rsvps (id,full_name,email,phone,attendance,guest_names,dietary,note,token_hash,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (rid,p.full_name,p.email,p.phone,p.attendance,json.dumps(p.guest_names,ensure_ascii=False),p.dietary,p.note,digest(token),now,now))
        row = db.execute('SELECT * FROM rsvps WHERE id=?',(rid,)).fetchone()
    return {'receipt': receipt(row), 'edit_token': token}

@app.get('/api/rsvp/{token}')
def read_personal(token: str, request: Request):
    rate_limit(request, 'read', 80, 3600)
    with conn() as db:
        row=db.execute('SELECT * FROM rsvps WHERE token_hash=?',(digest(token),)).fetchone()
    if not row:
        raise HTTPException(404,'Link privado não encontrado.')
    return receipt(row)

@app.put('/api/rsvp/{token}')
def update_personal(token: str, request: Request, p: RSVP):
    same_origin(request)
    rate_limit(request, 'edit', 24, 3600)
    p=clean(p)
    now=int(time.time())
    with conn() as db:
        row=db.execute('SELECT id FROM rsvps WHERE token_hash=?',(digest(token),)).fetchone()
        if not row:
            raise HTTPException(404,'Link privado não encontrado.')
        db.execute('''UPDATE rsvps SET full_name=?, email=?, phone=?, attendance=?, guest_names=?, dietary=?, note=?, updated_at=? WHERE id=?''',
          (p.full_name,p.email,p.phone,p.attendance,json.dumps(p.guest_names,ensure_ascii=False),p.dietary,p.note,now,row['id']))
        updated=db.execute('SELECT * FROM rsvps WHERE id=?',(row['id'],)).fetchone()
    return {'receipt':receipt(updated),'edit_token':token}

def is_admin(request:Request):
    if not ADMIN_PASSWORD or not SECRET or len(SECRET) < 24:
        return False
    cookie=request.cookies.get('nl_admin','')
    try:
        stamp, signature=cookie.split('.',1)
        if abs(int(time.time()) - int(stamp)) > 86400:
            return False
        correct=hmac.new(SECRET.encode(),stamp.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, correct)
    except (TypeError,ValueError):
        return False

def require_admin(request:Request):
    if not is_admin(request):
        raise HTTPException(401, 'Acesso reservado aos organizadores.')

class Login(BaseModel):
    password: str

@app.post('/api/admin/login')
def admin_login(request:Request, response:Response, credentials:Login):
    same_origin(request)
    rate_limit(request, 'login', 10, 600)
    if not ADMIN_PASSWORD or not SECRET or len(SECRET) < 24:
        raise HTTPException(503, 'Defina ADMIN_PASSWORD e SESSION_SECRET para habilitar o painel.')
    if not hmac.compare_digest(credentials.password, ADMIN_PASSWORD):
        raise HTTPException(401, 'Senha incorreta.')
    stamp=str(int(time.time()))
    signature=hmac.new(SECRET.encode(),stamp.encode(),hashlib.sha256).hexdigest()
    response.set_cookie('nl_admin',f'{stamp}.{signature}',max_age=86400,httponly=True,samesite='strict',secure=COOKIE_SECURE)
    return {'ok':True}

@app.post('/api/admin/logout')
def admin_logout(request:Request,response:Response):
    same_origin(request)
    response.delete_cookie('nl_admin',samesite='strict',secure=COOKIE_SECURE)
    return {'ok':True}

@app.get('/api/admin/responses')
def admin_responses(request:Request):
    require_admin(request)
    with conn() as db:
        rows=db.execute('SELECT * FROM rsvps ORDER BY updated_at DESC').fetchall()
    return [dict(receipt(r),id=r['id'],created_at=r['created_at']) for r in rows]

@app.get('/api/admin/export')
def admin_export(request:Request):
    require_admin(request)
    with conn() as db:
        rows=db.execute('SELECT * FROM rsvps ORDER BY full_name').fetchall()
    out=io.StringIO()
    writer=csv.writer(out)
    writer.writerow(['Nome','Email','Telefone','Presença','Acompanhantes','Nomes acompanhantes','Restrições','Mensagem','Criado','Atualizado'])
    for r in rows:
        writer.writerow([r['full_name'],r['email'],r['phone'],'Sim' if r['attendance']=='yes' else 'Não',len(json.loads(r['guest_names'])),'; '.join(json.loads(r['guest_names'])),r['dietary'],r['note'],r['created_at'],r['updated_at']])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="rsvp-naomi-luan.csv"'})

@app.get('/admin',include_in_schema=False)
def admin_page():
    return FileResponse(ROOT / 'static' / 'admin.html')