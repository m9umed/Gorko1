#!/usr/bin/env python3
# Mi server - no external packages needed. Run: python server.py
# Env vars: PORT, ADMIN_USER, ADMIN_PASS (defaults 1212 / 5555 - change them on your host!)
import http.server, json, sqlite3, os, time, base64, uuid, hashlib, re, threading, mimetypes

PORT = int(os.environ.get("PORT", 8000))
AU, AP = os.environ.get("ADMIN_USER", "1212"), os.environ.get("ADMIN_PASS", "5555")
D = os.path.dirname(os.path.abspath(__file__)); U = os.path.join(D, "uploads"); os.makedirs(U, exist_ok=True)
db = sqlite3.connect(os.path.join(D, "mi.db"), check_same_thread=False); db.row_factory = sqlite3.Row
L = threading.Lock(); ADM = set()
db.executescript("""
create table if not exists users(id integer primary key,name text unique,pw text,bio text default '',av text default '',created real,last real default 0,seen real default 0,frozen int default 0);
create table if not exists posts(id integer primary key,u int,kind text,media text,mt text,txt text,ts real);
create table if not exists likes(p int,u int,primary key(p,u));
create table if not exists comments(id integer primary key,p int,u int,txt text,ts real);
create table if not exists follows(a int,b int,primary key(a,b));
create table if not exists msgs(id integer primary key,f int,t int,txt text,media text,mt text,ts real,edited int default 0);
create table if not exists blocks(a int,b int,primary key(a,b));
create table if not exists restr(a int,b int,primary key(a,b));
create table if not exists chatdel(u int,o int,ts real,primary key(u,o));
create table if not exists notifs(id integer primary key,u int,txt text,ts real);
create table if not exists sess(tok text primary key,u int);""")

def row(s, a=()):
    with L: return [dict(r) for r in db.execute(s, a).fetchall()]
def run(s, a=()):
    with L:
        c = db.execute(s, a); db.commit(); return c.lastrowid
def Hs(p): return hashlib.sha256(("mi$" + p).encode()).hexdigest()
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}
def save(d):
    if not d or not d.startswith("data:"): return ""
    h, b = d.split(",", 1); e = EXT.get(h[5:].split(";")[0])
    if not e: return ""
    n = uuid.uuid4().hex + "." + e
    open(os.path.join(U, n), "wb").write(base64.b64decode(b)); return "/uploads/" + n
def MT(m): return "v" if m.endswith((".mp4", ".webm", ".mov")) else ("i" if m else "")
def N(u, t, me):
    if u != me: run("insert into notifs(u,txt,ts) values(?,?,?)", (u, t, time.time()))
def P(me, where, lim=60):
    return row("select p.*,u.name,u.av,(select count(*) from likes where p=p.id) likes,(select count(*) from likes where p=p.id and u=?) liked,(select count(*) from comments where p=p.id) cc from posts p join users u on u.id=p.u where u.frozen=0 and " + where + " order by p.id desc limit ?", (me, lim))
def wipe(i):
    for s in ["delete from posts where u=?1", "delete from likes where u=?1", "delete from comments where u=?1", "delete from follows where a=?1 or b=?1", "delete from msgs where f=?1 or t=?1", "delete from blocks where a=?1 or b=?1", "delete from restr where a=?1 or b=?1", "delete from sess where u=?1", "delete from notifs where u=?1", "delete from users where id=?1"]:
        run(s, (i,))
def auth(t):
    if t in ADM: return -1
    r = row("select u from sess where tok=?", (t,))
    if not r: return None
    x = row("select frozen from users where id=?", (r[0]["u"],))
    if not x or x[0]["frozen"]: return None
    run("update users set seen=? where id=?", (time.time(), r[0]["u"])); return r[0]["u"]

def act(a, d):
    now = time.time(); g = d.get
    if a == "reg":
        n, p = g("name", "").strip(), g("pw", "")
        if not re.fullmatch(r"[A-Za-z0-9_.]{3,20}", n) or len(p) < 4: return {"err": "اسم المستخدم 3-20 حرف انجليزي أو أرقام، وكلمة السر 4 أحرف على الأقل"}
        if n == AU: return {"err": "الاسم غير متاح"}
        try: run("insert into users(name,pw,created,last) values(?,?,?,?)", (n, Hs(p), now, now))
        except sqlite3.IntegrityError: return {"err": "اسم المستخدم مستخدم"}
        a = "login"
    if a == "login":
        n, p = g("name", ""), g("pw", "")
        if n == AU and p == AP:
            t = uuid.uuid4().hex; ADM.add(t); return {"t": t, "admin": 1}
        r = row("select * from users where name=? and pw=?", (n, Hs(p)))
        if not r: return {"err": "اسم المستخدم أو كلمة السر خاطئة"}
        if r[0]["frozen"]: return {"err": "هذا الحساب مجمّد"}
        t = uuid.uuid4().hex; run("insert into sess values(?,?)", (t, r[0]["id"])); run("update users set last=?,seen=? where id=?", (now, now, r[0]["id"]))
        return {"t": t, "me": {"id": r[0]["id"], "name": n, "av": r[0]["av"]}}
    u = auth(g("t"))
    if u is None: return {"err": "auth"}
    if u == -1:
        if a == "me": return {"admin": 1}
        if a == "adm":
            us = row("select id,name,created,last,seen,frozen from users order by id desc")
            return {"users": us, "total": len(us), "online": sum(1 for x in us if x["seen"] > now - 60 and not x["frozen"])}
        if a == "freeze": run("update users set frozen=? where id=?", (g("v", 1), g("id"))); return {}
        if a == "deluser": wipe(g("id")); return {}
        return {"err": "?"}
    BL = "(select b from blocks where a=%d union select a from blocks where b=%d)" % (u, u)
    if a == "me": return {"me": row("select id,name,av from users where id=?", (u,))[0]}
    if a == "feed":
        ids = "(select b from follows where a=%d union select %d)" % (u, u)
        return {"posts": P(u, "p.kind='post' and p.u in %s and p.u not in %s" % (ids, BL)), "stories": P(u, "p.kind='story' and p.ts>%f and p.u in %s and p.u not in %s" % (now - 86400, ids, BL), 100)}
    if a == "reels": return {"posts": P(u, "p.kind='reel' and p.u not in " + BL)}
    if a == "new":
        k, m = g("kind"), save(g("media"))
        if k not in ("post", "story", "reel") or (k != "post" and not m) or (not m and not g("txt", "").strip()): return {"err": "أضف ملفاً أو نصاً"}
        run("insert into posts(u,kind,media,mt,txt,ts) values(?,?,?,?,?,?)", (u, k, m, MT(m), g("txt", "")[:2000], now)); return {}
    if a == "editpost": run("update posts set txt=? where id=? and u=?", (g("txt", "")[:2000], g("id"), u)); return {}
    if a == "delpost": run("delete from posts where id=? and u=?", (g("id"), u)); run("delete from comments where p=?", (g("id"),)); return {}
    if a == "like":
        p = g("p")
        if row("select 1 from likes where p=? and u=?", (p, u)): run("delete from likes where p=? and u=?", (p, u))
        else:
            run("insert into likes values(?,?)", (p, u)); o = row("select u from posts where id=?", (p,))
            if o: N(o[0]["u"], "أعجب بمنشورك: " + row("select name from users where id=?", (u,))[0]["name"], u)
        return {"likes": row("select count(*) c from likes where p=?", (p,))[0]["c"], "liked": bool(row("select 1 from likes where p=? and u=?", (p, u)))}
    if a == "cmts":
        p = g("p")
        return {"c": row("select c.*,us.name,us.av from comments c join users us on us.id=c.u where c.p=?1 and (c.u=?2 or ?2=(select u from posts where id=?1) or c.u not in (select b from restr where a=(select u from posts where id=?1))) order by c.id", (p, u))}
    if a == "comment":
        t = g("txt", "").strip()[:500]
        if t:
            run("insert into comments(p,u,txt,ts) values(?,?,?,?)", (g("p"), u, t, now)); o = row("select u from posts where id=?", (g("p"),))
            if o: N(o[0]["u"], "علّق على منشورك: " + row("select name from users where id=?", (u,))[0]["name"], u)
        return {}
    if a == "delcmt": run("delete from comments where id=? and u=?", (g("id"), u)); return {}
    if a == "search":
        return {"us": row("select id,name,av,(select count(*) from follows where a=? and b=users.id) isf from users where name like ? and frozen=0 and id!=? and id not in " + BL + " limit 30", (u, "%" + g("q", "") + "%", u))}
    if a == "follow":
        i = g("id")
        if row("select 1 from follows where a=? and b=?", (u, i)): run("delete from follows where a=? and b=?", (u, i))
        else: run("insert into follows values(?,?)", (u, i)); N(i, "بدأ بمتابعتك: " + row("select name from users where id=?", (u,))[0]["name"], u)
        return {}
    if a in ("block", "restrict"):
        t = "blocks" if a == "block" else "restr"; i = g("id")
        if row("select 1 from %s where a=? and b=?" % t, (u, i)): run("delete from %s where a=? and b=?" % t, (u, i))
        else:
            run("insert into %s values(?,?)" % t, (u, i))
            if a == "block": run("delete from follows where (a=? and b=?) or (a=? and b=?)", (u, i, i, u))
        return {}
    if a == "lists":
        return {"bl": row("select id,name,av from users where id in (select b from blocks where a=?)", (u,)), "rs": row("select id,name,av from users where id in (select b from restr where a=?)", (u,))}
    if a == "profile":
        i = g("id", u); r = row("select id,name,bio,av from users where id=? and frozen=0", (i,))
        if not r or row("select 1 from blocks where a=? and b=?", (i, u)): return {"err": "الحساب غير موجود"}
        return {"u": r[0], "fers": row("select count(*) c from follows where b=?", (i,))[0]["c"], "fing": row("select count(*) c from follows where a=?", (i,))[0]["c"],
                "isf": bool(row("select 1 from follows where a=? and b=?", (u, i))), "isb": bool(row("select 1 from blocks where a=? and b=?", (u, i))), "isr": bool(row("select 1 from restr where a=? and b=?", (u, i))),
                "posts": P(u, "p.u=%d and p.kind in ('post','reel')" % int(i))}
    if a == "editprofile":
        n = g("name", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.]{3,20}", n) or n == AU: return {"err": "اسم مستخدم غير صالح"}
        av = save(g("av")) or row("select av from users where id=?", (u,))[0]["av"]
        try: run("update users set name=?,bio=?,av=? where id=?", (n, g("bio", "")[:300], av, u))
        except sqlite3.IntegrityError: return {"err": "اسم المستخدم مستخدم"}
        return {"me": row("select id,name,av from users where id=?", (u,))[0]}
    if a == "chats":
        cd = {r["o"]: r["ts"] for r in row("select o,ts from chatdel where u=?", (u,))}; out = {}
        for m in row("select * from msgs where f=? or t=? order by id", (u, u)):
            o = m["t"] if m["f"] == u else m["f"]
            if m["ts"] > cd.get(o, 0): out[o] = m
        res = []
        for o, m in sorted(out.items(), key=lambda x: -x[1]["id"]):
            x = row("select id,name,av from users where id=? and frozen=0", (o,))
            if x: res.append({**x[0], "last": m["txt"] or ("📎 صورة" if m["mt"] == "i" else "📎 فيديو"), "ts": m["ts"]})
        return {"chats": res}
    if a == "msgs":
        o = g("o"); cd = row("select ts from chatdel where u=? and o=?", (u, o))
        return {"m": row("select * from msgs where ((f=?1 and t=?2) or (f=?2 and t=?1)) and ts>?3 order by id", (u, o, cd[0]["ts"] if cd else 0))}
    if a == "send":
        o = g("o")
        if row("select 1 from blocks where (a=? and b=?) or (a=? and b=?)", (u, o, o, u)): return {"err": "لا يمكن إرسال رسالة لهذا المستخدم"}
        m = save(g("media")); t = g("txt", "").strip()[:2000]
        if m or t: run("insert into msgs(f,t,txt,media,mt,ts) values(?,?,?,?,?,?)", (u, o, t, m, MT(m), now))
        return {}
    if a == "editmsg": run("update msgs set txt=?,edited=1 where id=? and f=?", (g("txt", "")[:2000], g("id"), u)); return {}
    if a == "delmsg": run("delete from msgs where id=? and f=?", (g("id"), u)); return {}
    if a == "delchat": run("insert or replace into chatdel values(?,?,?)", (u, g("o"), now)); return {}
    if a == "notifs": return {"n": row("select * from notifs where u=? order by id desc limit 50", (u,))}
    return {"err": "?"}

class Hd(http.server.BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def do_GET(s):
        p = s.path.split("?")[0]
        f = os.path.join(D, "index.html") if p == "/" else os.path.join(U, os.path.basename(p)) if p.startswith("/uploads/") else None
        if not f or not os.path.isfile(f): s.send_error(404); return
        b = open(f, "rb").read(); ct = mimetypes.guess_type(f)[0] or "text/html"; st = 200; hd = {}
        if ct == "text/html": ct += "; charset=utf-8"
        m = re.match(r"bytes=(\d*)-(\d*)", s.headers.get("Range", ""))
        if m and p != "/":
            a0 = int(m.group(1) or 0); a1 = int(m.group(2)) if m.group(2) else len(b) - 1
            hd["Content-Range"] = "bytes %d-%d/%d" % (a0, a1, len(b)); b = b[a0:a1 + 1]; st = 206
        s.send_response(st); s.send_header("Content-Type", ct); s.send_header("Content-Length", len(b)); s.send_header("Accept-Ranges", "bytes")
        for k, v in hd.items(): s.send_header(k, v)
        s.end_headers(); s.wfile.write(b)
    def do_POST(s):
        try:
            n = int(s.headers.get("Content-Length", 0))
            if n > 80_000_000: raise ValueError
            d = json.loads(s.rfile.read(n)); r = act(d.get("a"), d)
        except Exception as e: r = {"err": "خطأ في الطلب"}
        b = json.dumps(r).encode(); s.send_response(200); s.send_header("Content-Type", "application/json"); s.send_header("Content-Length", len(b)); s.end_headers(); s.wfile.write(b)

if __name__ == "__main__":
    print("Mi running on port", PORT)
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Hd).serve_forever()
