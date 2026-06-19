import sqlite3
import os
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tools.db")
STATIC_DIR = os.path.join(BASE_DIR, "public")

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        phone TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS tools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        description TEXT,
        owner_id INTEGER NOT NULL,
        status TEXT DEFAULT 'available',
        image_url TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (owner_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id INTEGER NOT NULL,
        borrower_id INTEGER NOT NULL,
        status TEXT DEFAULT 'borrowed',
        borrowed_at TEXT DEFAULT (datetime('now','localtime')),
        returned_at TEXT,
        FOREIGN KEY (tool_id) REFERENCES tools(id),
        FOREIGN KEY (borrower_id) REFERENCES users(id)
    );
    """)

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO users (name, phone) VALUES (?, ?)",
            [
                ("张三", "13800000001"),
                ("李四", "13800000002"),
                ("王五", "13800000003"),
            ],
        )
        c.executemany(
            "INSERT INTO tools (name, category, description, owner_id, status) VALUES (?, ?, ?, ?, ?)",
            [
                ("电钻", "电动工具", "博世品牌电钻，含多种钻头", 1, "available"),
                ("梯子", "登高工具", "3米铝合金折叠梯", 2, "available"),
                ("活动扳手", "手动工具", "12寸大开口活动扳手", 1, "available"),
                ("万用表", "测量工具", "数字万用表，测量电压电流电阻", 3, "available"),
                ("电锯", "电动工具", "手持式电锯，切割木材", 2, "available"),
            ],
        )
    conn.commit()
    conn.close()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


def default_image(name):
    prompt = quote(name or "工具")
    return f"https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt={prompt}&image_size=square"


def parse_json_body(rfile, length):
    if length <= 0:
        return {}
    try:
        raw = rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


class Handler(BaseHTTPRequestHandler):
    server_version = "ToolSharing/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, rel_path):
        full = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
        if not full.startswith(os.path.normpath(STATIC_DIR)):
            return self._send_json(403, {"error": "forbidden"})
        if not os.path.isfile(full):
            index = os.path.join(STATIC_DIR, "index.html")
            if os.path.isfile(index):
                full = index
            else:
                return self._send_json(404, {"error": "not found"})
        try:
            with open(full, "rb") as f:
                body = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self._send_json(500, {"error": "read error"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if not path.startswith("/api"):
            rel = path[1:] if path.startswith("/") else path
            return self._send_file(rel)

        try:
            if path == "/api/users":
                return self.api_get_users()
            if path == "/api/tools":
                return self.api_get_tools(qs)
            if path == "/api/tools/categories":
                return self.api_get_categories()
            if path.startswith("/api/tools/") and path.endswith("/borrow") is False and path.endswith("/return") is False:
                tid = int(path.rsplit("/", 1)[-1])
                return self.api_get_tool_detail(tid)
            if path == "/api/orders":
                return self.api_get_orders(qs)
            return self._send_json(404, {"error": "API not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", "0") or "0")
        data = parse_json_body(self.rfile, length)

        try:
            if path == "/api/users":
                return self.api_create_user(data)
            if path == "/api/tools":
                return self.api_create_tool(data)
            if path.startswith("/api/tools/") and path.endswith("/borrow"):
                tid = int(path.replace("/api/tools/", "").replace("/borrow", ""))
                return self.api_borrow_tool(tid, data)
            if path.startswith("/api/tools/") and path.endswith("/return"):
                tid = int(path.replace("/api/tools/", "").replace("/return", ""))
                return self.api_return_tool(tid)
            return self._send_json(404, {"error": "API not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def api_get_users(self):
        conn = get_db()
        try:
            users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
            self._send_json(200, rows_to_list(users))
        finally:
            conn.close()

    def api_create_user(self, data):
        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        if not name:
            return self._send_json(400, {"error": "姓名不能为空"})
        conn = get_db()
        try:
            try:
                cur = conn.execute(
                    "INSERT INTO users (name, phone) VALUES (?, ?)", (name, phone)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return self._send_json(400, {"error": "用户名已存在"})
            user = conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
            self._send_json(201, row_to_dict(user))
        finally:
            conn.close()

    def api_get_tools(self, qs):
        status = (qs.get("status", [""])[0] or "").strip()
        category = (qs.get("category", [""])[0] or "").strip()
        keyword = (qs.get("keyword", [""])[0] or "").strip()
        conn = get_db()
        try:
            sql = """
                SELECT t.*, u.name AS owner_name
                FROM tools t LEFT JOIN users u ON t.owner_id = u.id WHERE 1=1
            """
            params = []
            if status:
                sql += " AND t.status = ?"
                params.append(status)
            if category:
                sql += " AND t.category = ?"
                params.append(category)
            if keyword:
                sql += " AND (t.name LIKE ? OR t.description LIKE ?)"
                params.extend([f"%{keyword}%", f"%{keyword}%"])
            sql += " ORDER BY t.id DESC"
            tools = conn.execute(sql, params).fetchall()
            result = []
            for t in tools:
                td = dict(t)
                td["image_url"] = td.get("image_url") or default_image(td.get("name"))
                result.append(td)
            self._send_json(200, result)
        finally:
            conn.close()

    def api_get_categories(self):
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT DISTINCT category FROM tools WHERE category IS NOT NULL AND category <> '' ORDER BY category"
            ).fetchall()
            self._send_json(200, [r["category"] for r in rows])
        finally:
            conn.close()

    def api_get_tool_detail(self, tool_id):
        conn = get_db()
        try:
            tool = conn.execute(
                "SELECT t.*, u.name AS owner_name, u.phone AS owner_phone FROM tools t LEFT JOIN users u ON t.owner_id = u.id WHERE t.id = ?",
                (tool_id,),
            ).fetchone()
            if tool is None:
                return self._send_json(404, {"error": "工具不存在"})
            td = dict(tool)
            td["image_url"] = td.get("image_url") or default_image(td.get("name"))
            history = conn.execute(
                "SELECT o.*, u.name AS borrower_name FROM orders o LEFT JOIN users u ON o.borrower_id = u.id WHERE o.tool_id = ? ORDER BY o.id DESC",
                (tool_id,),
            ).fetchall()
            self._send_json(200, {"tool": td, "history": rows_to_list(history)})
        finally:
            conn.close()

    def api_create_tool(self, data):
        name = (data.get("name") or "").strip()
        category = (data.get("category") or "").strip() or "其他"
        description = (data.get("description") or "").strip()
        owner_id = data.get("owner_id")
        if not name or not owner_id:
            return self._send_json(400, {"error": "工具名称和发布人不能为空"})
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO tools (name, category, description, owner_id, status) VALUES (?, ?, ?, ?, 'available')",
                (name, category, description, int(owner_id)),
            )
            conn.commit()
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (cur.lastrowid,)).fetchone()
            self._send_json(201, row_to_dict(tool))
        finally:
            conn.close()

    def api_borrow_tool(self, tool_id, data):
        borrower_id = data.get("borrower_id")
        if not borrower_id:
            return self._send_json(400, {"error": "请选择借用人"})
        borrower_id = int(borrower_id)

        conn = get_db()
        try:
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if tool is None:
                return self._send_json(404, {"error": "工具不存在"})
            if tool["owner_id"] == borrower_id:
                return self._send_json(400, {"error": "不能借用自己发布的工具"})
            if tool["status"] != "available":
                return self._send_json(400, {"error": "该工具当前不可借用（已借出）"})

            pending = conn.execute(
                "SELECT id FROM orders WHERE tool_id=? AND status='borrowed'",
                (tool_id,),
            ).fetchone()
            if pending:
                return self._send_json(400, {"error": "该工具已有未归还的借用记录，无法重复借用"})

            conn.execute("UPDATE tools SET status='borrowed' WHERE id=?", (tool_id,))
            cur = conn.execute(
                "INSERT INTO orders (tool_id, borrower_id, status) VALUES (?, ?, 'borrowed')",
                (tool_id, borrower_id),
            )
            conn.commit()
            order = conn.execute(
                """SELECT o.*, t.name AS tool_name, u.name AS borrower_name
                   FROM orders o
                   LEFT JOIN tools t ON o.tool_id = t.id
                   LEFT JOIN users u ON o.borrower_id = u.id
                   WHERE o.id = ?""",
                (cur.lastrowid,),
            ).fetchone()
            self._send_json(201, row_to_dict(order))
        finally:
            conn.close()

    def api_return_tool(self, tool_id):
        conn = get_db()
        try:
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if tool is None:
                return self._send_json(404, {"error": "工具不存在"})
            if tool["status"] != "borrowed":
                return self._send_json(400, {"error": "该工具当前未被借出，无需归还"})

            order = conn.execute(
                "SELECT * FROM orders WHERE tool_id=? AND status='borrowed' ORDER BY id DESC LIMIT 1",
                (tool_id,),
            ).fetchone()
            if order is None:
                conn.execute("UPDATE tools SET status='available' WHERE id=?", (tool_id,))
                conn.commit()
                return self._send_json(200, {"message": "工具状态已重置为可借"})

            conn.execute(
                "UPDATE orders SET status='returned', returned_at=datetime('now','localtime') WHERE id=?",
                (order["id"],),
            )
            conn.execute("UPDATE tools SET status='available' WHERE id=?", (tool_id,))
            conn.commit()

            updated = conn.execute(
                """SELECT o.*, t.name AS tool_name, u.name AS borrower_name
                   FROM orders o
                   LEFT JOIN tools t ON o.tool_id = t.id
                   LEFT JOIN users u ON o.borrower_id = u.id
                   WHERE o.id = ?""",
                (order["id"],),
            ).fetchone()
            self._send_json(200, row_to_dict(updated))
        finally:
            conn.close()

    def api_get_orders(self, qs):
        user_id = qs.get("user_id", [None])[0]
        tool_id = qs.get("tool_id", [None])[0]
        status = (qs.get("status", [""])[0] or "").strip()

        sql = """
            SELECT o.*, t.name AS tool_name, u.name AS borrower_name,
                   ow.name AS owner_name
            FROM orders o
            LEFT JOIN tools t ON o.tool_id = t.id
            LEFT JOIN users u ON o.borrower_id = u.id
            LEFT JOIN users ow ON t.owner_id = ow.id
            WHERE 1=1
        """
        params = []
        if user_id:
            uid = int(user_id)
            sql += " AND (o.borrower_id = ? OR t.owner_id = ?)"
            params.extend([uid, uid])
        if tool_id:
            sql += " AND o.tool_id = ?"
            params.append(int(tool_id))
        if status:
            sql += " AND o.status = ?"
            params.append(status)
        sql += " ORDER BY o.id DESC"

        conn = get_db()
        try:
            orders = conn.execute(sql, params).fetchall()
            self._send_json(200, rows_to_list(orders))
        finally:
            conn.close()


def main():
    init_db()
    port = 5000
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("工具共享平台已启动: http://localhost:5000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("已停止")
        server.server_close()


if __name__ == "__main__":
    main()
