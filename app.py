import ctypes
from datetime import datetime
import os
import re
import shutil
import subprocess
import sys
import traceback

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
import mysql.connector
import pandas as pd
from pythonping import ping as python_ping
import requests
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "mitrabuana01"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Mitra01!",
    "database": "Dashboard",
}

RESEND_API_URL = "http://10.15.42.126:8040/services/xray"


def connect_db():
    return mysql.connector.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        autocommit=True,
        use_pure=True,
        auth_plugin="mysql_native_password",
    )


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin):

    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password


def get_user_by_username(username):
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        return user
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        return user
    finally:
        conn.close()


@login_manager.user_loader
def load_user(user_id):
    user = get_user_by_id(user_id)
    if user:
        return User(user["id"], user["username"], user["password"])
    return None


def serialize_dict(r):
    item = dict(r)
    for key, val in item.items():
        if hasattr(val, "strftime"):
            item[key] = val.strftime("%Y-%m-%d %H:%M:%S")
        elif hasattr(val, "total_seconds"):
            total = int(val.total_seconds())
            item[key] = (
                f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
            )
    return item


def process_log_row(row):
    item = serialize_dict(row)

    scan_id = (
        item.get("scan_id") or item.get("id_scan") or item.get("id") or "-"
    )
    container = str(
        item.get("container")
        or item.get("no_container")
        or item.get("container_no")
        or ""
    ).strip()
    plate = str(
        item.get("plate")
        or item.get("plat")
        or item.get("no_plat")
        or ""
    ).strip()

    try:
        image_count = int(
            item.get("image_count") or item.get("total_gambar") or 0
        )
    except (ValueError, TypeError):
        image_count = 0

    status = str(item.get("status") or "NOK").upper()
    raw_detail = str(
        item.get("detail")
        or item.get("keterangan")
        or item.get("reason")
        or ""
    ).strip()

    if status == "OK":
        if raw_detail and raw_detail not in ["-", "NONE", "NULL", ""]:
            keterangan = raw_detail
        else:
            keterangan = "Pengiriman Pertama Langsung Sukses"
    elif not container or container in ["-", "NONE", "NULL", "UNDEFINED"]:
        keterangan = "Nomor Container Tidak Terdeteksi"
    elif image_count < 6:
        keterangan = f"Jumlah Gambar Kurang ({image_count}/6 File)"
    elif raw_detail and raw_detail not in [
        "Format / Data Tidak Valid",
        "Format/Data Tidak Valid",
        "NOK",
        "",
    ]:
        keterangan = raw_detail
    else:
        keterangan = "Format / Data Tidak Valid"

    item["id"] = item.get("id") or scan_id
    item["scan_id"] = scan_id
    item["container"] = (
        container if (container and container not in ["-", "NONE", "NULL"]) else "-"
    )
    item["plate"] = plate if plate else "-"
    item["plat"] = plate if plate else "-"
    item["image_count"] = image_count
    item["status"] = status
    item["detail"] = keterangan
    item["keterangan"] = keterangan
    item["jam_scan"] = item.get("jam_scan") or item.get("time") or "-"

    return item


def build_logs_query(
    status=None,
    search=None,
    filter_option="newest",
    limit=1000,
    start_date=None,
    end_date=None,
):
    query = "SELECT * FROM logs"
    where_clauses = []
    params = []

    if status == "ok":
        where_clauses.append("status = %s")
        params.append("OK")
    elif status == "nok":
        where_clauses.append("status <> %s")
        params.append("OK")

    if search:
        where_clauses.append(
            "(container LIKE %s OR plate LIKE %s OR scan_id LIKE %s OR status LIKE %s OR detail LIKE %s)"
        )
        s = f"%{search}%"
        params.extend([s, s, s, s, s])

    if start_date and end_date:
        where_clauses.append("DATE(jam_scan) BETWEEN %s AND %s")
        params.extend([start_date, end_date])
    elif start_date:
        where_clauses.append("DATE(jam_scan) = %s")
        params.append(start_date)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    if filter_option == "oldest":
        query += " ORDER BY jam_scan ASC"
    elif filter_option == "reason" and status == "nok":
        query += " ORDER BY detail ASC, jam_scan DESC"
    else:
        query += " ORDER BY jam_scan DESC"

    if limit > 0:
        query += f" LIMIT {limit}"

    return query, params


def fetch_logs(
    status=None,
    search=None,
    filter_option="newest",
    limit=1000,
    start_date=None,
    end_date=None,
):
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        query, params = build_logs_query(
            status, search, filter_option, limit, start_date, end_date
        )
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return [process_log_row(r) for r in rows]
    finally:
        conn.close()


def check_device_status(ip_address, port=21, timeout=2):
    try:
        result = python_ping(ip_address, count=2, timeout=timeout)
        if result.success():
            return {
                "status": "online",
                "response_time": f"{result.rtt_avg_ms:.1f}ms",
            }
        else:
            return {"status": "offline", "response_time": "Ping gagal"}
    except Exception as e:
        return {"status": "offline", "response_time": str(e)}


def get_shared_folder_usage(shared_path):
    try:
        if os.name == "nt":
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            total_free = ctypes.c_ulonglong(0)

            success = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(shared_path),
                ctypes.byref(free_bytes),
                ctypes.byref(total_bytes),
                ctypes.byref(total_free),
            )

            if success:
                total_gb = total_bytes.value / (1024**3)
                free_gb = free_bytes.value / (1024**3)
                free_percent = (
                    round((free_gb / total_gb) * 100, 1) if total_gb > 0 else 0
                )
                return {
                    "total_gb": round(total_gb, 2),
                    "free_gb": round(free_gb, 2),
                    "free_percent": free_percent,
                }

        usage = shutil.disk_usage(shared_path)
        total_gb = usage.total / (1024**3)
        free_gb = usage.free / (1024**3)
        free_percent = (
            round((free_gb / total_gb) * 100, 1) if total_gb > 0 else 0
        )
        return {
            "total_gb": round(total_gb, 2),
            "free_gb": round(free_gb, 2),
            "free_percent": free_percent,
        }
    except Exception as e:
        print(f"Gagal membaca kapasitas {shared_path}: {e}")
        return {"total_gb": 0, "free_gb": 0, "free_percent": 0}


def get_dashboard_metrics():
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT response_time FROM device_status 
            WHERE device_name = 'Watcher Service' 
            AND response_time >= NOW() - INTERVAL 30 SECOND
        """)
        watcher_online = cursor.fetchone() is not None

        device_status = {}
        try:
            cursor.execute(
                "SELECT device_name, ip_address, status, response_time FROM device_status"
            )
            db_devices = cursor.fetchall()
            for row in db_devices:
                device_status[row["device_name"]] = {
                    "ip": row["ip_address"],
                    "status": row["status"],
                    "response_time": row["response_time"],
                }
        except Exception as e:
            print(f"Error fetching device status: {e}")

        cursor.execute("SELECT COUNT(*) as ok_count FROM logs WHERE status='OK'")
        ok = cursor.fetchone()["ok_count"] or 0

        cursor.execute(
            "SELECT COUNT(*) as nok_count FROM logs WHERE status<>'OK'"
        )
        nok = cursor.fetchone()["nok_count"] or 0

        cursor.execute(
            "SELECT COUNT(*) as failed_count FROM logs WHERE folder_status='FAILED'"
        )
        failed_count = cursor.fetchone()["failed_count"] or 0

        cursor.execute("""
            SELECT
                COUNT(*) as today_total,
                COALESCE(SUM(IF(status='OK',1,0)), 0) as today_ok,
                COALESCE(SUM(IF(status<>'OK',1,0)), 0) as today_nok
            FROM logs
            WHERE DATE(jam_scan) = CURDATE()
        """)
        today_stats = cursor.fetchone()

        if today_stats:
            today_stats["today_ok"] = int(today_stats["today_ok"] or 0)
            today_stats["today_nok"] = int(today_stats["today_nok"] or 0)
            today_stats["today_total"] = int(today_stats["today_total"] or 0)

        cursor.execute("""
            SELECT COUNT(*) as real_today 
            FROM real_scans 
            WHERE scan_date LIKE CONCAT(CURDATE(), '%') OR DATE(scan_date) = CURDATE()
        """)
        real_today_row = cursor.fetchone()
        real_scan_today = (
            int(real_today_row["real_today"] or 0) if real_today_row else 0
        )

        shared_path = r"\\10.15.42.90\d"
        storage_info = get_shared_folder_usage(shared_path)

        cursor.close()
        conn.close()

        total_scans = ok + nok
        success_rate = (
            round((ok / total_scans * 100), 1) if total_scans > 0 else 0.0
        )

        return {
            "watcher_online": watcher_online,
            "ok": ok,
            "nok": nok,
            "failed_count": failed_count,
            "today_stats": today_stats,
            "real_scan_today": real_scan_today,
            "ping": device_status,
            "success_rate": success_rate,
            "storage": storage_info,
        }
    except Exception as e:
        print(f"Error in get_dashboard_metrics: {e}")
        traceback.print_exc()
        return {
            "watcher_online": False,
            "ok": 0,
            "nok": 0,
            "failed_count": 0,
            "today_stats": {"today_total": 0, "today_ok": 0, "today_nok": 0},
            "real_scan_today": 0,
            "ping": {},
            "success_rate": 0.0,
            "storage": {"total_gb": 0, "free_gb": 0, "free_percent": 0},
        }


def interpret_resend_response_success(response, raw_text):
    """Fungsi Validasi 2-Lapis Mutlak: HTTP Status + NPCT1 Flag."""
    if response is None or not response.ok:
        return False, "HTTP_ERROR"
    if not raw_text:
        return False, "EMPTY_RESPONSE"

    try:
        data = response.json()
        result_code = data.get("resultCode", False)
        npct1_resp = str(data.get("RESPON_NPCT1", "")).upper()

        if result_code is True and npct1_resp == "OK":
            return True, "NPCT1_OK"
        elif npct1_resp == "NOK":
            return False, "NPCT1_NOK"
        elif result_code is False:
            desc = (
                data.get("resultDesc")
                or data.get("message")
                or "Ditolak Server Pusat"
            )
            return False, f"REJECTED: {desc}"
        else:
            return False, f"RESPON_UNKNOWN ({npct1_resp})"
    except Exception:
        text = str(raw_text).strip().lower()
        if 'respon_npct1": "ok"' in text or 'respon_npct1":"ok"' in text:
            return True, "NPCT1_OK"
        return False, "INVALID_JSON_RESPONSE"


# ---------------------------------------------------------
# AUTH ROUTES
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user and check_password_hash(user["password"], password):
            login_user(User(user["id"], user["username"], user["password"]))
            return redirect(url_for("index_v2"))
        else:
            flash("Username atau password salah!", "danger")
    return render_template("login_v2.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------
# PAGE NAVIGATION ROUTES
# ---------------------------------------------------------
@app.route("/", endpoint="index")
@app.route("/v2", endpoint="index_v2")
@login_required
def index():
    try:
        search = request.args.get("search", request.args.get("q", "")).strip()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()
        limit = int(request.args.get("limit", 100))

        logs = fetch_logs(
            search=search,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        metrics = get_dashboard_metrics()

        return render_template(
            "index_v2.html",
            logs=logs,
            metrics=metrics,
            search=search,
            start_date=start_date,
            end_date=end_date,
            now=datetime.now(),
        )
    except Exception as e:
        print(f"Error in index route: {e}")
        traceback.print_exc()
        return f"Error: {str(e)}", 500


@app.route("/real-server", endpoint="real_server_page")
@app.route("/v2/real-server", endpoint="real_server_page_v2")
@login_required
def real_server_page():
    metrics = get_dashboard_metrics()
    return render_template("data_real_server.html", metrics=metrics)


@app.route("/detail/<status>", endpoint="detail_status")
@app.route("/v2/detail/<status>", endpoint="detail_status_v2")
@login_required
def detail_status(status):
    if status.lower() not in ("ok", "nok"):
        return "Invalid status", 400

    search = request.args.get("search", request.args.get("q", "")).strip()
    filter_option = request.args.get("filter", "newest")
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    limit = int(request.args.get("limit", 2000))

    logs = fetch_logs(
        status=status.lower(),
        search=search,
        filter_option=filter_option,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )
    metrics = get_dashboard_metrics()

    return render_template(
        "detail_status_v2.html",
        logs=logs,
        status=status.lower(),
        search=search,
        query_q=search,
        filter_option=filter_option,
        start_date=start_date,
        end_date=end_date,
        metrics=metrics,
    )


@app.route("/export", endpoint="export_page")
@app.route("/v2/export", endpoint="export_page_v2")
@login_required
def export_page_v2():
    return render_template("export_v2.html")


@app.route("/rescan", endpoint="rescan_checker")
@app.route("/v2/rescan", endpoint="rescan_checker_v2")
@login_required
def rescan_checker_v2():
    return render_template("rescan_v2.html")


@app.route("/analytics", endpoint="analytics_page")
@app.route("/v2/analytics", endpoint="analytics_page_v2")
@login_required
def analytics_page():
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                DATE_FORMAT(jam_scan, '%d/%m') as tgl,
                COALESCE(SUM(IF(status='OK', 1, 0)), 0) as total_ok,
                COALESCE(SUM(IF(status<>'OK', 1, 0)), 0) as total_nok
            FROM logs
            WHERE jam_scan >= CURDATE() - INTERVAL 30 DAY
            GROUP BY DATE(jam_scan), DATE_FORMAT(jam_scan, '%d/%m')
            ORDER BY MIN(jam_scan) ASC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        labels = [str(r["tgl"]) for r in rows]
        ok_data = [int(r["total_ok"]) for r in rows]
        nok_data = [int(r["total_nok"]) for r in rows]

        return render_template(
            "analytics_v2.html",
            labels=labels,
            ok_data=ok_data,
            nok_data=nok_data,
        )
    except Exception as e:
        print(f"Error in analytics_page: {e}")
        traceback.print_exc()
        return f"Error: {str(e)}", 500


# ---------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------
@app.route("/api/v2/real-scans")
@login_required
def api_v2_real_scans():
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT * FROM real_scans 
            WHERE scan_date LIKE CONCAT(CURDATE(), '%') 
               OR DATE(scan_date) = CURDATE()
            ORDER BY id DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()

        processed = []
        for r in rows:
            item = serialize_dict(r)
            cam_str = item.get("camera_images") or ""
            item["camera_list"] = (
                [c.strip() for c in cam_str.split(",") if c.strip()]
                if cam_str
                else []
            )
            processed.append(item)

        return (
            jsonify(
                {
                    "success": True,
                    "data": processed,
                    "total": len(processed),
                    "today_count": len(processed),
                }
            ),
            200,
        )
    except Exception as e:
        print(f"Error in api_v2_real_scans: {e}")
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "data": [],
                    "today_count": 0,
                }
            ),
            500,
        )
    finally:
        conn.close()


@app.route("/api/v2/real-scans/filter")
@login_required
def api_v2_real_scans_filter():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    search = request.args.get("search", request.args.get("q", "")).strip()

    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        where_clauses = []
        params = []

        if start_date and end_date:
            where_clauses.append("scan_date BETWEEN %s AND %s")
            params.extend([start_date, end_date])
        elif start_date:
            where_clauses.append("scan_date = %s")
            params.append(start_date)

        if search:
            where_clauses.append(
                "(folder_name LIKE %s OR main_image LIKE %s OR icon_image LIKE %s OR folder_path LIKE %s)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s])

        query = "SELECT * FROM real_scans"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY created_at DESC, scan_date DESC, id DESC LIMIT 5000"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        processed = []
        for r in rows:
            item = serialize_dict(r)
            cam_str = item.get("camera_images") or ""
            item["camera_list"] = (
                [c.strip() for c in cam_str.split(",") if c.strip()]
                if cam_str
                else []
            )
            processed.append(item)

        cursor.close()
        return jsonify(processed)
    except Exception as e:
        print(f"Error in api_v2_real_scans_filter: {e}")
        return jsonify([])
    finally:
        conn.close()


@app.route("/api/v2/live-logs")
@login_required
def api_v2_live_logs():
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("CREATE INDEX idx_jam_scan ON logs(jam_scan)")
        except Exception:
            pass

        query = """
            SELECT * FROM logs 
            WHERE jam_scan >= NOW() - INTERVAL 24 HOUR 
            ORDER BY jam_scan DESC 
            LIMIT 3000
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()

        logs_data = [process_log_row(row) for row in rows]
        metrics = get_dashboard_metrics()

        return (
            jsonify(
                {
                    "logs": logs_data,
                    "total_24h": len(logs_data),
                    "today_stats": metrics.get(
                        "today_stats",
                        {"today_ok": 0, "today_nok": 0, "today_total": 0},
                    ),
                }
            ),
            200,
        )
    except Exception as e:
        print(f"Error in api_v2_live_logs: {e}")
        return (
            jsonify(
                {
                    "error": str(e),
                    "logs": [],
                    "today_stats": {
                        "today_ok": 0,
                        "today_nok": 0,
                        "today_total": 0,
                    },
                }
            ),
            500,
        )
    finally:
        conn.close()


@app.route("/api/analytics/hourly")
@login_required
def api_hourly_analytics():
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                HOUR(jam_scan) AS hr,
                COALESCE(SUM(IF(status='OK', 1, 0)), 0) AS ok_count,
                COALESCE(SUM(IF(status<>'OK', 1, 0)), 0) AS nok_count
            FROM logs
            WHERE DATE(jam_scan) = CURDATE()
            GROUP BY HOUR(jam_scan)
            ORDER BY hr ASC
        """
        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        hours_data = {i: {"ok": 0, "nok": 0} for i in range(24)}
        for row in results:
            hr = int(row["hr"])
            if hr in hours_data:
                hours_data[hr]["ok"] = int(row["ok_count"] or 0)
                hours_data[hr]["nok"] = int(row["nok_count"] or 0)

        labels = [f"{str(i).zfill(2)}:00" for i in range(24)]
        ok_series = [hours_data[i]["ok"] for i in range(24)]
        nok_series = [hours_data[i]["nok"] for i in range(24)]

        return jsonify({"labels": labels, "ok": ok_series, "nok": nok_series})
    except Exception as e:
        print(f"Error in api_hourly_analytics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/analytics/monthly")
@login_required
def api_monthly_analytics():
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                DATE_FORMAT(jam_scan, '%d/%m') as tgl,
                COALESCE(SUM(IF(status='OK', 1, 0)), 0) as total_ok,
                COALESCE(SUM(IF(status<>'OK', 1, 0)), 0) as total_nok
            FROM logs
            WHERE jam_scan >= CURDATE() - INTERVAL 30 DAY
            GROUP BY DATE(jam_scan), DATE_FORMAT(jam_scan, '%d/%m')
            ORDER BY MIN(jam_scan) ASC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        labels = [str(r["tgl"]) for r in rows]
        ok_series = [int(r["total_ok"]) for r in rows]
        nok_series = [int(r["total_nok"]) for r in rows]

        return (
            jsonify({"labels": labels, "ok": ok_series, "nok": nok_series}),
            200,
        )
    except Exception as e:
        print(f"Error in api_monthly_analytics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/resend/<scan_id>", methods=["POST"])
@app.route("/api/resend_data/<scan_id>", methods=["POST"])
@login_required
def api_resend(scan_id):
    """Fungsi Resend Otomatis 1-Klik dari Tabel Data Hasil Pengiriman (logs)."""
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM logs WHERE scan_id = %s OR id = %s LIMIT 1",
            (scan_id, scan_id),
        )
        row = cursor.fetchone()

        if not row:
            cursor.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"ID Scan {scan_id} tidak ditemukan di DB lokal.",
                    }
                ),
                404,
            )

        log_item = process_log_row(row)

        picno = str(log_item.get("scan_id", "")).strip()
        jam_scan_str = str(log_item.get("jam_scan", "")).strip()

        # Auto-generate ftp_path dari PICNO / Jam Scan
        if len(picno) >= 21:
            dev_id = picno[:9]
            yyyy = picno[9:13]
            mmdd = picno[13:17]
            hhmm = picno[17:21]
            ftp_path = f"/{dev_id}/{yyyy}/{mmdd}/{hhmm}/"
        else:
            try:
                dt = datetime.strptime(jam_scan_str, "%Y-%m-%d %H:%M:%S")
                ftp_path = f"/62001FS01/{dt.strftime('%Y')}/{dt.strftime('%m%d')}/{dt.strftime('%H%M')}/"
            except Exception:
                ftp_path = "/62001FS01/2026/1110/1800/"

        container_clean = log_item.get("container", "")
        if container_clean in ["-", "NONE", "NULL", "UNDEFINED"]:
            container_clean = ""

        plate_clean = log_item.get("plate", "")
        if plate_clean in ["-", "NONE", "NULL"]:
            plate_clean = ""

        image_count = log_item.get("image_count", 0)

        image_msg = (
            f"<IDR>"
            f"<HEADER>"
            f"<PICNO>{picno}</PICNO>"
            f"<SCANTIME>{jam_scan_str}</SCANTIME>"
            f"<CONTAINER_NO>{container_clean}</CONTAINER_NO>"
            f"<TRUCK_NO>{plate_clean}</TRUCK_NO>"
            f"</HEADER>"
            f"<BODY>"
            f"<SCANIMG_COUNT>{image_count}</SCANIMG_COUNT>"
            f"</BODY>"
            f"</IDR>"
        )

        payload = {"ftp_path": ftp_path, "image_msg": image_msg}

        headers = {"Content-Type": "application/json"}

        response = requests.post(
            RESEND_API_URL, json=payload, headers=headers, timeout=15
        )
        resp_text = response.text or ""

        is_success, reason_code = interpret_resend_response_success(
            response, resp_text
        )

        if is_success:
            old_detail = log_item.get("detail", "NOK")
            new_detail = f"Resend Otomatis Berhasil (Awalnya: {old_detail})"

            cursor.execute(
                """
                UPDATE logs 
                SET status = 'OK', detail = %s, jam_scan = NOW()
                WHERE scan_id = %s OR id = %s
            """,
                (new_detail, scan_id, scan_id),
            )

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Resend ID Scan {scan_id} BERHASIL! NPCT1 Merespon OK.",
                        "status_code": response.status_code,
                        "response_text": resp_text[:200],
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Server Pusat Menolak Data ({reason_code}): {resp_text[:150]}",
                    }
                ),
                400,
            )

    except requests.exceptions.Timeout:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Koneksi Timeout saat mengirim ke {RESEND_API_URL}",
                }
            ),
            504,
        )
    except requests.exceptions.RequestException as req_err:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Gagal terhubung ke API Server Pusat ({RESEND_API_URL}): {str(req_err)}",
                }
            ),
            500,
        )
    except Exception as e:
        print(f"Error in api_resend: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/manual-resend", methods=["POST"])
@login_required
def api_manual_resend():
    """API Endpoint Khusus Resend Manual (Data Ngambang yang tidak ada di DB Lokal)."""
    try:
        data = request.get_json(silent=True) or {}
        ftp_path = str(data.get("ftp_path") or "").strip()
        image_msg = str(data.get("image_msg") or "").strip()
        task_id = str(data.get("task_id") or "MANUAL_RESEND").strip()

        if not ftp_path or not image_msg:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "FTP Path dan XML Payload (image_msg) tidak boleh kosong!",
                    }
                ),
                400,
            )

        payload = {"ftp_path": ftp_path, "image_msg": image_msg}

        headers = {"Content-Type": "application/json"}

        response = requests.post(
            RESEND_API_URL, json=payload, headers=headers, timeout=20
        )
        resp_text = response.text or ""

        is_success, reason_code = interpret_resend_response_success(
            response, resp_text
        )

        if is_success:
            return (
                jsonify(
                    {
                        "success": True,
                        "code": reason_code,
                        "message": f"Resend Manual Task [{task_id}] BERHASIL! NPCT1 Merespon OK.",
                        "status_code": response.status_code,
                        "response_text": resp_text[:300],
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "code": reason_code,
                        "error": f"Resend Gagal ({reason_code}): {resp_text[:250]}",
                        "status_code": response.status_code,
                        "response_text": resp_text[:300],
                    }
                ),
                400,
            )

    except requests.exceptions.Timeout:
        return (
            jsonify(
                {
                    "success": False,
                    "code": "TIMEOUT",
                    "error": f"Koneksi Timeout saat mengirim ke {RESEND_API_URL}",
                }
            ),
            504,
        )
    except requests.exceptions.RequestException as req_err:
        return (
            jsonify(
                {
                    "success": False,
                    "code": "NETWORK_ERROR",
                    "error": f"Gagal terhubung ke API Server Pusat ({RESEND_API_URL}): {str(req_err)}",
                }
            ),
            500,
        )
    except Exception as e:
        traceback.print_exc()
        return (
            jsonify({"success": False, "code": "ERROR", "error": str(e)}),
            500,
        )


@app.route("/api/dashboard-metrics")
@login_required
def api_dashboard_metrics():
    metrics = get_dashboard_metrics()
    return jsonify(metrics)


@app.route("/api/logs/latest")
@login_required
def api_logs_latest():
    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 50")
        rows = cursor.fetchall()
        serialized = [process_log_row(row) for row in rows]
        cursor.close()
        return jsonify(serialized)
    finally:
        conn.close()


@app.route("/api/logs/filter")
@login_required
def api_logs_filter():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    status = request.args.get("status", "all")
    search = request.args.get("search", request.args.get("q", "")).strip()

    if not start_date or not end_date:
        return jsonify({"error": "start_date dan end_date diperlukan"}), 400

    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        where_clauses = []
        params = []

        if status == "ok":
            where_clauses.append("status = %s")
            params.append("OK")
        elif status == "nok":
            where_clauses.append("status <> %s")
            params.append("OK")

        where_clauses.append("DATE(jam_scan) BETWEEN %s AND %s")
        params.extend([start_date, end_date])

        if search:
            where_clauses.append(
                "(container LIKE %s OR plate LIKE %s OR scan_id LIKE %s OR status LIKE %s OR detail LIKE %s)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s, s])

        query = "SELECT * FROM logs"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY jam_scan DESC LIMIT 5000"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        serialized = [process_log_row(row) for row in rows]

        cursor.close()
        return jsonify(serialized)
    finally:
        conn.close()


# ---------------------------------------------------------
# EXPORT EXCEL DUAL FUNCTIONALITY (LOGS / REAL SCANS)
# ---------------------------------------------------------
@app.route("/export/excel")
@login_required
def export_excel():
    data_type = request.args.get("data_type", "logs")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    status = request.args.get("status", "all")
    search = request.args.get("search", request.args.get("q", "")).strip()

    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        where_clauses = []
        params = []

        if data_type == "real_scans":
            if start_date and end_date:
                where_clauses.append("scan_date BETWEEN %s AND %s")
                params.extend([start_date, end_date])
            elif start_date:
                where_clauses.append("scan_date = %s")
                params.append(start_date)

            if search:
                where_clauses.append(
                    "(folder_name LIKE %s OR main_image LIKE %s OR icon_image LIKE %s OR folder_path LIKE %s)"
                )
                s = f"%{search}%"
                params.extend([s, s, s, s])

            query = "SELECT id, folder_name AS 'ID Folder Scan', scan_date AS 'Tanggal Scan', main_image AS 'File X-Ray Utama', icon_image AS 'File Icon', camera_images AS 'Daftar Foto Kamera', created_at AS 'Waktu Record' FROM real_scans"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            query += " ORDER BY created_at DESC, scan_date DESC, id DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return (
                    "Tidak ada data Real Server untuk periode yang dipilih.",
                    200,
                )

            df = pd.DataFrame(rows)
            filename = (
                f"export_real_scans_{start_date or 'all'}_{end_date or ''}.xlsx"
            )
            df.to_excel(filename, index=False)
            return send_file(filename, as_attachment=True)

        else:
            if status == "ok":
                where_clauses.append("status = %s")
                params.append("OK")
            elif status == "nok":
                where_clauses.append("status <> %s")
                params.append("OK")

            if start_date and end_date:
                where_clauses.append("DATE(jam_scan) BETWEEN %s AND %s")
                params.extend([start_date, end_date])
            elif start_date:
                where_clauses.append("DATE(jam_scan) = %s")
                params.append(start_date)
            else:
                where_clauses.append(
                    "DATE(jam_scan) >= CURDATE() - INTERVAL 7 DAY"
                )

            if search:
                where_clauses.append(
                    "(container LIKE %s OR plate LIKE %s OR scan_id LIKE %s OR status LIKE %s OR detail LIKE %s)"
                )
                s = f"%{search}%"
                params.extend([s, s, s, s, s])

            query = "SELECT * FROM logs"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            query += " ORDER BY jam_scan DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return (
                    "Tidak ada data pengiriman untuk periode yang dipilih.",
                    200,
                )

            processed_rows = [process_log_row(r) for r in rows]
            df = pd.DataFrame(processed_rows)
            status_label = f"_{status}" if status != "all" else ""
            filename = f"export_logs{status_label}_{start_date or 'last7days'}_{end_date or ''}.xlsx"
            df.to_excel(filename, index=False)
            return send_file(filename, as_attachment=True)

    finally:
        conn.close()


@app.route("/api/rescan/check", methods=["POST"])
@login_required
def api_rescan_check():
    data = request.get_json()
    if not data or "containers" not in data:
        return jsonify({"error": "Tidak ada data container"}), 400

    containers = data["containers"]
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if not isinstance(containers, list) or len(containers) == 0:
        return jsonify({"error": "List container kosong"}), 400

    containers = containers[:200]
    results = []

    conn = connect_db()
    try:
        cursor = conn.cursor(dictionary=True)
        for ctr in containers:
            ctr_clean = ctr.strip().upper()
            if not re.match(r"^[A-Z]{4}\d{7}$", ctr_clean):
                results.append({"container": ctr_clean, "records": []})
                continue

            query = "SELECT * FROM logs WHERE container = %s"
            params = [ctr_clean]

            if start_date and end_date:
                query += " AND DATE(jam_scan) BETWEEN %s AND %s"
                params.extend([start_date, end_date])
            elif start_date:
                query += " AND DATE(jam_scan) = %s"
                params.append(start_date)

            query += " ORDER BY jam_scan DESC"
            cursor.execute(query, params)

            rows = cursor.fetchall()
            serialized = [process_log_row(row) for row in rows]
            results.append({"container": ctr_clean, "records": serialized})
        cursor.close()
    except Exception as e:
        print(f"[rescan] DB error: {e}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    finally:
        conn.close()

    return jsonify({"results": results})


# ---------------------------------------------------------
# RUN SERVER
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)