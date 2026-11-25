# -*- coding: utf-8 -*-
"""
سيرفر قلب جليدي 💙❄️
التشغيل:   python server.py
ثم افتح:   http://127.0.0.1:5000

المتطلبات:
    pip install flask flask-socketio flask-cors simple-websocket
"""
import glob
import html
import os
import sqlite3
import time
from contextlib import closing

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'icy_heart.db')
PORT = int(os.environ.get('PORT', 5000))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'icy_heart_secret_2026')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')


# ───────────────────────── قاعدة البيانات ─────────────────────────

def db():
    return sqlite3.connect(DB_PATH, timeout=10)


def init_db():
    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (username TEXT PRIMARY KEY, password TEXT, avatar TEXT DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS friends
                     (user1 TEXT, user2 TEXT, UNIQUE(user1, user2))''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocks
                     (blocker TEXT, blocked TEXT, UNIQUE(blocker, blocked))''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      sender TEXT,
                      receiver TEXT,
                      text TEXT,
                      is_read INTEGER DEFAULT 0,
                      edited INTEGER DEFAULT 0,
                      deleted_for_all INTEGER DEFAULT 0,
                      deleted_by_sender INTEGER DEFAULT 0,
                      deleted_by_receiver INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS statuses
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT,
                      text TEXT,
                      bg_color TEXT,
                      created_at REAL)''')


init_db()


def err(message):
    return jsonify({'status': 'error', 'message': message})


def check_pw(stored, given):
    """يرجع (هل صحيحة، هل تحتاج ترقية للتشفير). يدعم الحسابات القديمة بكلمات مرور نصية."""
    stored = stored or ''
    if stored.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored, given), False
    return stored == given, True


# ───────────────────────── الصفحة الرئيسية ─────────────────────────

def find_index():
    """يبحث عن index.html بجانب السيرفر، وإلا في مجلد التشغيل، وإلا أي ملف index*.html."""
    folders = [BASE_DIR]
    if os.getcwd() != BASE_DIR:
        folders.append(os.getcwd())
    for d in folders:
        p = os.path.join(d, 'index.html')
        if os.path.isfile(p):
            return p
    for d in folders:
        found = sorted(glob.glob(os.path.join(d, 'index*.html')))
        if found:
            return found[0]
    return None


@app.route('/')
@app.route('/index.html')
def index():
    path = find_index()
    if not path:
        files = ' ، '.join(sorted(os.listdir(BASE_DIR)))
        page = (
            '<html dir="rtl" lang="ar"><meta charset="utf-8">'
            '<body style="font-family:sans-serif;background:#0f172a;color:#f0f9ff;padding:24px">'
            '<h2>السيرفر شغّال، لكن ما لقيت ملف index.html</h2>'
            f'<p>مجلد السيرفر: <code dir="ltr">{html.escape(BASE_DIR)}</code></p>'
            f'<p>الملفات الموجودة فيه: <code dir="ltr">{html.escape(files)}</code></p>'
            '<p>ضع index.html في نفس هذا المجلد ثم حدّث الصفحة.</p></body></html>'
        )
        return Response(page, status=404, mimetype='text/html')
    with open(path, 'rb') as f:
        data = f.read()
    resp = Response(data, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/ping')
def ping():
    return jsonify({'status': 'ok'})


# ───────────────────────── الحسابات ─────────────────────────

@app.route('/auth', methods=['POST'])
def auth():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    if not username or not password:
        return err('يرجى إدخال اسم المستخدم وكلمة المرور')
    if len(username) > 30:
        return err('اسم المستخدم طويل جداً (الحد الأقصى 30 حرفاً)')

    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("SELECT password, avatar FROM users WHERE username=?", (username,))
        user = c.fetchone()

        if user:
            ok, upgrade = check_pw(user[0], password)
            if not ok:
                return err('كلمة المرور غير صحيحة!')
            if upgrade:
                c.execute("UPDATE users SET password=? WHERE username=?",
                          (generate_password_hash(password), username))
            return jsonify({'status': 'success', 'username': username, 'avatar': user[1] or ''})

        c.execute("INSERT INTO users (username, password, avatar) VALUES (?, ?, '')",
                  (username, generate_password_hash(password)))
    return jsonify({'status': 'success', 'username': username, 'avatar': ''})


@app.route('/update_profile', methods=['POST'])
def update_profile():
    data = request.get_json(silent=True) or {}
    old_u = (data.get('old_username') or '').strip()
    new_u = (data.get('new_username') or '').strip()
    avatar = data.get('avatar')

    if not new_u:
        return err('اسم المستخدم لا يمكن أن يكون فارغاً')
    if len(new_u) > 30:
        return err('اسم المستخدم طويل جداً (الحد الأقصى 30 حرفاً)')
    if avatar is not None:
        if not isinstance(avatar, str) or len(avatar) > 600_000 or \
                (avatar and not avatar.startswith('data:image/')):
            return err('صورة غير صالحة')

    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE username=?", (old_u,))
        if not c.fetchone():
            return err('الحساب غير موجود')

        if new_u != old_u:
            c.execute("SELECT 1 FROM users WHERE username=?", (new_u,))
            if c.fetchone():
                return err('اسم المستخدم مستخدم بالفعل!')
            c.execute("UPDATE users SET username=? WHERE username=?", (new_u, old_u))
            c.execute("UPDATE friends SET user1=? WHERE user1=?", (new_u, old_u))
            c.execute("UPDATE friends SET user2=? WHERE user2=?", (new_u, old_u))
            c.execute("UPDATE messages SET sender=? WHERE sender=?", (new_u, old_u))
            c.execute("UPDATE messages SET receiver=? WHERE receiver=?", (new_u, old_u))
            c.execute("UPDATE statuses SET username=? WHERE username=?", (new_u, old_u))
            c.execute("UPDATE blocks SET blocker=? WHERE blocker=?", (new_u, old_u))
            c.execute("UPDATE blocks SET blocked=? WHERE blocked=?", (new_u, old_u))

        if avatar is not None:
            c.execute("UPDATE users SET avatar=? WHERE username=?", (avatar, new_u))

        c.execute("SELECT avatar FROM users WHERE username=?", (new_u,))
        updated_avatar = c.fetchone()[0] or ''
    return jsonify({'status': 'success', 'username': new_u, 'avatar': updated_avatar})


# ───────────────────────── الأصدقاء ─────────────────────────

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '').strip()
    current_user = request.args.get('user', '')
    with closing(db()) as conn:
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE username LIKE ? AND username != ? LIMIT 30",
                  (f'%{query}%', current_user))
        results = [row[0] for row in c.fetchall()]
    return jsonify({'users': results})


@app.route('/add_friend', methods=['POST'])
def add_friend():
    data = request.get_json(silent=True) or {}
    user1 = data.get('user')
    user2 = data.get('friend')
    if not user1 or not user2 or user1 == user2:
        return err('طلب غير صالح')
    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE username IN (?, ?)", (user1, user2))
        if c.fetchone()[0] != 2:
            return err('المستخدم غير موجود')
        c.execute("INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)", (user1, user2))
        c.execute("INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)", (user2, user1))
    return jsonify({'status': 'success'})


@app.route('/friends', methods=['GET'])
def get_friends():
    user = request.args.get('user')
    with closing(db()) as conn:
        c = conn.cursor()
        c.execute('''SELECT u.username, u.avatar FROM friends f
                     JOIN users u ON f.user2 = u.username
                     WHERE f.user1=?''', (user,))
        friends = [{'username': row[0], 'avatar': row[1] or ''} for row in c.fetchall()]
    return jsonify({'friends': friends})


# ───────────────────────── الرسائل ─────────────────────────

@app.route('/messages', methods=['GET'])
def get_messages():
    u1 = request.args.get('u1')
    u2 = request.args.get('u2')
    with closing(db()) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM blocks WHERE blocker=? AND blocked=?", (u1, u2))
        blocked_by_me = bool(c.fetchone())
        c.execute("SELECT 1 FROM blocks WHERE blocker=? AND blocked=?", (u2, u1))
        blocked_me = bool(c.fetchone())

        c.execute('''SELECT id, sender, receiver, text, is_read, edited, deleted_for_all,
                            deleted_by_sender, deleted_by_receiver
                     FROM messages
                     WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)
                     ORDER BY id ASC''', (u1, u2, u2, u1))
        msgs = []
        for row in c.fetchall():
            if row[1] == u1 and row[7] == 1:
                continue
            if row[2] == u1 and row[8] == 1:
                continue
            msgs.append({
                'id': row[0], 'sender': row[1], 'receiver': row[2],
                'text': '' if row[6] else row[3],
                'is_read': row[4], 'edited': row[5], 'deleted_for_all': row[6],
            })
    return jsonify({'messages': msgs, 'blocked_by_me': blocked_by_me, 'blocked_me': blocked_me})


@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    data = request.get_json(silent=True) or {}
    u, f = data.get('user'), data.get('friend')
    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("UPDATE messages SET deleted_by_sender=1 WHERE sender=? AND receiver=?", (u, f))
        c.execute("UPDATE messages SET deleted_by_receiver=1 WHERE receiver=? AND sender=?", (u, f))
    return jsonify({'status': 'success'})


@app.route('/toggle_block', methods=['POST'])
def toggle_block():
    data = request.get_json(silent=True) or {}
    u, f = data.get('user'), data.get('friend')
    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM blocks WHERE blocker=? AND blocked=?", (u, f))
        if c.fetchone():
            c.execute("DELETE FROM blocks WHERE blocker=? AND blocked=?", (u, f))
            blocked = False
        else:
            c.execute("INSERT OR IGNORE INTO blocks (blocker, blocked) VALUES (?, ?)", (u, f))
            blocked = True
    return jsonify({'status': 'success', 'blocked': blocked})


# ───────────────────────── الحالات (24 ساعة) ─────────────────────────

@app.route('/statuses', methods=['GET', 'POST'])
def statuses():
    now = time.time()
    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("DELETE FROM statuses WHERE created_at < ?", (now - 86400,))

        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            user = data.get('user')
            text = (data.get('text') or '').strip()
            bg = data.get('bg_color') or ''
            if not user or not text:
                return err('اكتب نص الحالة أولاً')
            if len(text) > 500:
                return err('الحالة طويلة جداً')
            if not bg.startswith('linear-gradient(') or 'url' in bg.lower() or len(bg) > 200:
                bg = 'linear-gradient(135deg, #0284c7, #1e3a8a)'
            c.execute("INSERT INTO statuses (username, text, bg_color, created_at) VALUES (?, ?, ?, ?)",
                      (user, text, bg, now))
            return jsonify({'status': 'success'})

        user = request.args.get('user')
        c.execute('''SELECT s.username, s.text, s.bg_color, s.created_at, u.avatar
                     FROM statuses s
                     JOIN users u ON s.username = u.username
                     WHERE s.username = ? OR s.username IN (SELECT user2 FROM friends WHERE user1 = ?)
                     ORDER BY s.created_at DESC''', (user, user))
        items = []
        for row in c.fetchall():
            hours_left = max(1, int((row[3] + 86400 - now) // 3600))
            items.append({'username': row[0], 'text': row[1], 'bg_color': row[2],
                          'hours_left': hours_left, 'avatar': row[4] or ''})
    return jsonify({'statuses': items})


# ───────────────────────── Socket.IO ─────────────────────────

@socketio.on('join')
def on_join(data):
    username = (data or {}).get('username')
    if username:
        join_room(username)


@socketio.on('send_message')
def handle_message(data):
    data = data or {}
    sender, receiver = data.get('sender'), data.get('receiver')
    text = (data.get('text') or '').strip()
    if not sender or not receiver or not text or len(text) > 4000:
        return

    with closing(db()) as conn, conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM blocks WHERE (blocker=? AND blocked=?) OR (blocker=? AND blocked=?)",
                  (sender, receiver, receiver, sender))
        if c.fetchone():
            return
        c.execute("INSERT INTO messages (sender, receiver, text) VALUES (?, ?, ?)",
                  (sender, receiver, text))
        msg_id = c.lastrowid

    payload = {'id': msg_id, 'sender': sender, 'receiver': receiver, 'text': text,
               'is_read': 0, 'edited': 0, 'deleted_for_all': 0}
    emit('receive_message', payload, room=receiver)
    emit('receive_message', payload, room=sender)


@socketio.on('mark_read')
def mark_read(data):
    data = data or {}
    sender, receiver = data.get('sender'), data.get('receiver')
    if not sender or not receiver:
        return
    with closing(db()) as conn, conn:
        conn.execute("UPDATE messages SET is_read=1 WHERE sender=? AND receiver=? AND is_read=0",
                     (sender, receiver))
    emit('messages_read', {'by': receiver}, room=sender)


@socketio.on('edit_message')
def edit_message(data):
    data = data or {}
    msg_id, sender, receiver = data.get('id'), data.get('sender'), data.get('receiver')
    new_text = (data.get('text') or '').strip()
    if not msg_id or not sender or not new_text or len(new_text) > 4000:
        return
    with closing(db()) as conn, conn:
        cur = conn.execute(
            "UPDATE messages SET text=?, edited=1 WHERE id=? AND sender=? AND deleted_for_all=0",
            (new_text, msg_id, sender))
        if cur.rowcount == 0:
            return
    payload = {'id': msg_id, 'text': new_text, 'edited': 1}
    emit('message_updated', payload, room=sender)
    emit('message_updated', payload, room=receiver)


@socketio.on('delete_message')
def delete_message(data):
    data = data or {}
    msg_id, mode, user, friend = data.get('id'), data.get('mode'), data.get('user'), data.get('friend')
    if not msg_id or not user:
        return
    with closing(db()) as conn, conn:
        if mode == 'everyone':
            cur = conn.execute("UPDATE messages SET deleted_for_all=1 WHERE id=? AND sender=?",
                               (msg_id, user))
            if cur.rowcount == 0:
                return
        else:
            cur = conn.execute("UPDATE messages SET deleted_by_sender=1 WHERE id=? AND sender=?",
                               (msg_id, user))
            if cur.rowcount == 0:
                return

    if mode == 'everyone':
        payload = {'id': msg_id, 'deleted_for_all': 1, 'text': ''}
        emit('message_updated', payload, room=user)
        if friend:
            emit('message_updated', payload, room=friend)
    else:
        emit('message_removed', {'id': msg_id}, room=user)


if __name__ == '__main__':
    index_path = find_index()
    print('=' * 50)
    print('❄️  سيرفر قلب جليدي')
    print('مجلد السيرفر :', BASE_DIR)
    print('ملف الصفحة   :', index_path or '⚠️ غير موجود! ضع index.html بجانب server.py')
    print(f'افتح الرابط   : http://127.0.0.1:{PORT}')
    print('=' * 50)
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False, allow_unsafe_werkzeug=True)
