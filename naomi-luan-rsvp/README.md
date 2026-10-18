# Naomi & Luan — RSVP no Render (ramo isolado)

Fonte público do site, sem qualquer senha. O serviço precisa da variável de ambiente `DATABASE_URL` com a **Internal Database URL** do Postgres gratuito já criado no Render. Em seguida redeploy; sem URL a página existe mas o formulário fica desabilitado, para que nenhuma confirmação seja perdida.

No Render: service → Environment → Add Environment Variable → DATABASE_URL → copie a Internal Database URL do banco Postgres do mesmo workspace, sem colar senhas nesta conversa. Configure `SESSION_SECRET` com aleatoriedade forte e `ADMIN_PASSWORD` pessoal antes de abrir o painel. Use `COOKIE_SECURE=true`. A database gratuita expira em 17/11/2026: exporte confirmações e migre para um banco persistente antes disso.

Build command: `cd naomi-luan-rsvp && pip install -r requirements.txt`
Start command: `cd naomi-luan-rsvp && uvicorn server:app --host 0.0.0.0 --port $PORT`

Site: / ; painel protegido: /admin ; verificação simples: /api/status