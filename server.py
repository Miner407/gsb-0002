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
        credit_score INTEGER DEFAULT 100,
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

    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        confirmed_at TEXT,
        FOREIGN KEY (tool_id) REFERENCES tools(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS credit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL,
        ref_type TEXT,
        ref_id INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    try:
        c.execute("SELECT credit_score FROM users LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE users ADD COLUMN credit_score INTEGER DEFAULT 100")
        c.execute("UPDATE users SET credit_score = 100 WHERE credit_score IS NULL")

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO users (name, phone, credit_score) VALUES (?, ?, ?)",
            [
                ("张三", "13800000001", 100),
                ("李四", "13800000002", 100),
                ("王五", "13800000003", 100),
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


def update_credit(conn, user_id, delta, reason="", ref_type=None, ref_id=None):
    conn.execute(
        "UPDATE users SET credit_score = MAX(0, MIN(200, credit_score + ?)) WHERE id = ?",
        (delta, user_id),
    )
    if reason:
        conn.execute(
            "INSERT INTO credit_logs (user_id, delta, reason, ref_type, ref_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, delta, reason, ref_type, ref_id),
        )


def process_reservations_after_return(conn, tool_id):
    earliest = conn.execute(
        "SELECT * FROM reservations WHERE tool_id=? AND status='pending' ORDER BY created_at ASC LIMIT 1",
        (tool_id,),
    ).fetchone()
    if earliest:
        conn.execute(
            "UPDATE reservations SET status='confirmed', confirmed_at=datetime('now','localtime') WHERE id=?",
            (earliest["id"],),
        )
        conn.execute("UPDATE tools SET status='reserved' WHERE id=?", (tool_id,))
    else:
        conn.execute("UPDATE tools SET status='available' WHERE id=?", (tool_id,))


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
            if path.startswith("/api/users/") and path.endswith("/credit-logs"):
                uid = int(path.replace("/api/users/", "").replace("/credit-logs", ""))
                return self.api_get_user_credit_logs(uid)
            if path == "/api/tools":
                return self.api_get_tools(qs)
            if path == "/api/tools/categories":
                return self.api_get_categories()
            if path == "/api/reservations":
                return self.api_get_my_reservations(qs)
            if path.startswith("/api/tools/"):
                parts = path.replace("/api/tools/", "").split("/")
                tid = int(parts[0])
                if len(parts) == 2 and parts[1] == "reservations":
                    return self.api_get_tool_reservations(tid)
                if len(parts) == 1 and parts[0].isdigit():
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
            if path.startswith("/api/tools/") and path.endswith("/reserve"):
                tid = int(path.replace("/api/tools/", "").replace("/reserve", ""))
                return self.api_reserve_tool(tid, data)
            if path.startswith("/api/reservations/") and path.endswith("/cancel"):
                rid = int(path.replace("/api/reservations/", "").replace("/cancel", ""))
                return self.api_cancel_reservation(rid, data)
            if path.startswith("/api/reservations/") and path.endswith("/pickup"):
                rid = int(path.replace("/api/reservations/", "").replace("/pickup", ""))
                return self.api_pickup_reservation(rid)
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

    def api_get_user_credit_logs(self, user_id):
        conn = get_db()
        try:
            logs = conn.execute(
                "SELECT * FROM credit_logs WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (user_id,),
            ).fetchall()
            self._send_json(200, rows_to_list(logs))
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
                    "INSERT INTO users (name, phone, credit_score) VALUES (?, ?, 100)",
                    (name, phone),
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
                SELECT t.*, u.name AS owner_name, u.credit_score AS owner_credit
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
                res_count = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM reservations WHERE tool_id=? AND status IN ('pending','confirmed')",
                    (td["id"],),
                ).fetchone()
                td["reservation_count"] = res_count["cnt"] if res_count else 0
                confirmed = conn.execute(
                    """SELECT r.*, u.name AS user_name, u.credit_score AS user_credit
                       FROM reservations r LEFT JOIN users u ON r.user_id = u.id
                       WHERE r.tool_id=? AND r.status='confirmed'""",
                    (td["id"],),
                ).fetchone()
                td["confirmed_reservation"] = row_to_dict(confirmed)
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
                "SELECT t.*, u.name AS owner_name, u.phone AS owner_phone, u.credit_score AS owner_credit FROM tools t LEFT JOIN users u ON t.owner_id = u.id WHERE t.id = ?",
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
            reservations = conn.execute(
                """SELECT r.*, u.name AS user_name, u.credit_score AS user_credit
                   FROM reservations r LEFT JOIN users u ON r.user_id = u.id
                   WHERE r.tool_id=? AND r.status IN ('pending','confirmed')
                   ORDER BY r.created_at ASC""",
                (tool_id,),
            ).fetchall()
            self._send_json(200, {"tool": td, "history": rows_to_list(history), "reservations": rows_to_list(reservations)})
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

            if tool["status"] == "available":
                pending = conn.execute(
                    "SELECT id FROM orders WHERE tool_id=? AND status='borrowed'",
                    (tool_id,),
                ).fetchone()
                if pending:
                    return self._send_json(400, {"error": "该工具已有未归还的借用记录"})
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

            elif tool["status"] == "reserved":
                confirmed = conn.execute(
                    "SELECT * FROM reservations WHERE tool_id=? AND status='confirmed'",
                    (tool_id,),
                ).fetchone()
                if not confirmed:
                    return self._send_json(400, {"error": "该工具没有待确认的预约"})
                if confirmed["user_id"] != borrower_id:
                    return self._send_json(400, {"error": "该工具已为其他用户预约，请等待轮到你"})
                conn.execute(
                    "UPDATE reservations SET status='completed' WHERE id=?",
                    (confirmed["id"],),
                )
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
            else:
                return self._send_json(400, {"error": "该工具当前不可借用（已借出）"})
        finally:
            conn.close()

    def api_return_tool(self, tool_id):
        conn = get_db()
        try:
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if tool is None:
                return self._send_json(404, {"error": "工具不存在"})
            if tool["status"] not in ("borrowed", "reserved"):
                return self._send_json(400, {"error": "该工具当前无需归还"})

            order = conn.execute(
                "SELECT * FROM orders WHERE tool_id=? AND status='borrowed' ORDER BY id DESC LIMIT 1",
                (tool_id,),
            ).fetchone()

            if order is None:
                if tool["status"] == "reserved":
                    confirmed = conn.execute(
                        "SELECT * FROM reservations WHERE tool_id=? AND status='confirmed'",
                        (tool_id,),
                    ).fetchone()
                    if confirmed:
                        update_credit(conn, confirmed["user_id"], -5, "待取用预约被取消", "reservation", confirmed["id"])
                    conn.execute(
                        "UPDATE reservations SET status='cancelled' WHERE tool_id=? AND status IN ('pending','confirmed')",
                        (tool_id,),
                    )
                conn.execute("UPDATE tools SET status='available' WHERE id=?", (tool_id,))
                conn.commit()
                return self._send_json(200, {"message": "工具状态已重置为可借"})

            borrowed_at = datetime.strptime(order["borrowed_at"], "%Y-%m-%d %H:%M:%S") if order["borrowed_at"] else None
            is_overdue = False
            if borrowed_at and (datetime.now() - borrowed_at).days > 7:
                is_overdue = True
                update_credit(conn, order["borrower_id"], -10, "逾期归还工具", "order", order["id"])
            else:
                update_credit(conn, order["borrower_id"], 5, "按时归还工具", "order", order["id"])

            conn.execute(
                "UPDATE orders SET status='returned', returned_at=datetime('now','localtime') WHERE id=?",
                (order["id"],),
            )
            process_reservations_after_return(conn, tool_id)
            conn.commit()

            updated = conn.execute(
                """SELECT o.*, t.name AS tool_name, u.name AS borrower_name
                   FROM orders o
                   LEFT JOIN tools t ON o.tool_id = t.id
                   LEFT JOIN users u ON o.borrower_id = u.id
                   WHERE o.id = ?""",
                (order["id"],),
            ).fetchone()
            result = row_to_dict(updated)
            result["is_overdue"] = is_overdue
            result["credit_delta"] = -10 if is_overdue else 5
            self._send_json(200, result)
        finally:
            conn.close()

    def api_reserve_tool(self, tool_id, data):
        user_id = data.get("user_id")
        if not user_id:
            return self._send_json(400, {"error": "请选择预约人"})
        user_id = int(user_id)
        conn = get_db()
        try:
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if tool is None:
                return self._send_json(404, {"error": "工具不存在"})
            if tool["owner_id"] == user_id:
                return self._send_json(400, {"error": "不能预约自己发布的工具"})
            if tool["status"] not in ("borrowed", "reserved"):
                return self._send_json(400, {"error": "该工具当前可借用，无需预约"})
            dup = conn.execute(
                "SELECT id FROM reservations WHERE tool_id=? AND user_id=? AND status IN ('pending','confirmed')",
                (tool_id, user_id),
            ).fetchone()
            if dup:
                return self._send_json(400, {"error": "您已预约该工具，请勿重复预约"})

            cur = conn.execute(
                "INSERT INTO reservations (tool_id, user_id, status) VALUES (?, ?, 'pending')",
                (tool_id, user_id),
            )
            conn.commit()
            reservation = conn.execute(
                """SELECT r.*, t.name AS tool_name, u.name AS user_name
                   FROM reservations r
                   LEFT JOIN tools t ON r.tool_id = t.id
                   LEFT JOIN users u ON r.user_id = u.id
                   WHERE r.id = ?""",
                (cur.lastrowid,),
            ).fetchone()
            self._send_json(201, row_to_dict(reservation))
        finally:
            conn.close()

    def api_cancel_reservation(self, reservation_id, data):
        user_id = data.get("user_id")
        if not user_id:
            return self._send_json(400, {"error": "请提供用户ID"})
        user_id = int(user_id)
        conn = get_db()
        try:
            res = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if res is None:
                return self._send_json(404, {"error": "预约记录不存在"})
            if res["user_id"] != user_id:
                return self._send_json(400, {"error": "只能取消自己的预约"})
            if res["status"] not in ("pending", "confirmed"):
                return self._send_json(400, {"error": "该预约已无法取消"})

            was_confirmed = res["status"] == "confirmed"
            tool_id = res["tool_id"]
            conn.execute(
                "UPDATE reservations SET status='cancelled' WHERE id=?",
                (reservation_id,),
            )

            if was_confirmed:
                update_credit(conn, user_id, -5, "取消待取用预约", "reservation", reservation_id)
                process_reservations_after_return(conn, tool_id)

            conn.commit()
            self._send_json(200, {"message": "预约已取消", "credit_penalty": -5 if was_confirmed else 0})
        finally:
            conn.close()

    def api_pickup_reservation(self, reservation_id):
        conn = get_db()
        try:
            res = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if res is None:
                return self._send_json(404, {"error": "预约记录不存在"})
            if res["status"] != "confirmed":
                return self._send_json(400, {"error": "该预约尚未确认，无法取用"})

            tool_id = res["tool_id"]
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if tool["status"] != "reserved":
                return self._send_json(400, {"error": "工具状态异常"})

            conn.execute(
                "UPDATE reservations SET status='completed' WHERE id=?",
                (reservation_id,),
            )
            conn.execute("UPDATE tools SET status='borrowed' WHERE id=?", (tool_id,))
            cur = conn.execute(
                "INSERT INTO orders (tool_id, borrower_id, status) VALUES (?, ?, 'borrowed')",
                (tool_id, res["user_id"]),
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

    def api_get_tool_reservations(self, tool_id):
        conn = get_db()
        try:
            tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if tool is None:
                return self._send_json(404, {"error": "工具不存在"})
            reservations = conn.execute(
                """SELECT r.*, u.name AS user_name, u.credit_score AS user_credit
                   FROM reservations r LEFT JOIN users u ON r.user_id = u.id
                   WHERE r.tool_id=? AND r.status IN ('pending','confirmed')
                   ORDER BY r.created_at ASC""",
                (tool_id,),
            ).fetchall()
            self._send_json(200, rows_to_list(reservations))
        finally:
            conn.close()

    def api_get_my_reservations(self, qs):
        user_id = qs.get("user_id", [None])[0]
        status = (qs.get("status", [""])[0] or "").strip()
        if not user_id:
            return self._send_json(400, {"error": "请提供用户ID"})
        uid = int(user_id)

        sql = """
            SELECT r.*, t.name AS tool_name, t.status AS tool_status, t.owner_id,
                   u.name AS user_name, ow.name AS owner_name
            FROM reservations r
            LEFT JOIN tools t ON r.tool_id = t.id
            LEFT JOIN users u ON r.user_id = u.id
            LEFT JOIN users ow ON t.owner_id = ow.id
            WHERE r.user_id = ?
        """
        params = [uid]
        if status:
            sql += " AND r.status = ?"
            params.append(status)
        else:
            sql += " AND r.status IN ('pending','confirmed')"
        sql += " ORDER BY r.created_at ASC"

        conn = get_db()
        try:
            reservations = conn.execute(sql, params).fetchall()
            self._send_json(200, rows_to_list(reservations))
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
