import os
import sys
import re
import time
import sqlite3
import datetime
import httpx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.sqlite")
TOKEN_FILE = os.path.join(BASE_DIR, ".bot_token")

# In-memory session state for interactive flow
# user_sessions[chat_id] = { "step": "...", "data": {...} }
user_sessions = {}

POPULAR_SERIES = {
    "APPLE": ["IPHONE 15 PINK", "IPHONE 15 BLUE", "IPHONE 15 BLACK", "IPHONE 14 BLUE", "IPHONE 14 PUTIH", "IPHONE 14 HITAM", "IPHONE 13 HITAM", "IPHONE 17 PROMAX"],
    "POCO": ["POCO X8 PRO (12+512)", "POCO F7", "POCO C71", "POCO C81 PRO"],
    "SAMSUNG": ["GALAXY A55 5G", "GALAXY A35", "GALAXY S24 ULTRA", "GALAXY S23 FE"],
    "INFINIX": ["INFINIX XPAD", "INFINIX NOTE 40 PRO", "INFINIX GT 20 PRO", "INFINIX HOT 40 PRO"],
    "ITEL": ["ITEL S23+", "ITEL P55 5G", "ITEL RS4", "ITEL A70"],
    "XIAOMI": ["REDMI PAD 2", "REDMI NOTE 13 PRO", "REDMI 13C"]
}

def get_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token.strip()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            t = f.read().strip()
            if t:
                return t
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    return None

def format_rupiah(num):
    return f"Rp {int(num):,}".replace(",", ".")

def parse_nominal(raw_str):
    if not raw_str:
        return None
    s = raw_str.strip().lower().replace(",", ".")
    mult = 1
    if "jt" in s or "juta" in s:
        mult = 1_000_000
        s = re.sub(r'[^0-9.]', '', s)
    elif "k" in s or "rb" in s or "ribu" in s:
        mult = 1_000
        s = re.sub(r'[^0-9.]', '', s)
    else:
        if s.count(".") > 1:
            s = s.replace(".", "")
        elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
            s = s.replace(".", "")
    try:
        return float(s) * mult
    except Exception:
        return None

# HTTP Client Session Pool for ultra-fast Telegram responses
api_client = None

def get_api_client():
    global api_client
    if api_client is None or api_client.is_closed:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0)
        api_client = httpx.Client(timeout=10.0, limits=limits)
    return api_client

def send_tg_message(bot_token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = get_api_client().post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        print("Error sending message:", e)
        return None

def answer_callback(bot_token, callback_id, text=None):
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        get_api_client().post(url, json=payload, timeout=5)
    except Exception:
        pass

def edit_message(bot_token, chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        get_api_client().post(url, json=payload, timeout=10)
    except Exception:
        pass

# --- DB HELPERS ---
def add_ready_stock(merk, nama, harga_beli, pembayaran):
    tgl = datetime.date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO penjualan (tanggal, nama_produk, merk, qty, harga_beli, harga_jual, pembayaran, keuntungan, margin, status, tanggal_beli)
        VALUES (?, ?, ?, 1, ?, 0, ?, 0, 0, 'READY', ?)
    ''', (tgl, nama.strip().upper(), merk.strip().upper(), harga_beli, pembayaran.strip().upper(), tgl))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_ready_stocks(limit=10):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM penjualan WHERE status = 'READY' ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def sell_ready_stock(item_id, harga_jual, pembayaran):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM penjualan WHERE id = ?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    item = dict(row)
    tgl_jual = datetime.date.today().strftime("%Y-%m-%d")
    untung = (harga_jual - item["harga_beli"]) * item["qty"]
    margin = (untung / (harga_jual * item["qty"])) if harga_jual > 0 else 0
    c.execute('''
        UPDATE penjualan
        SET status = 'TERJUAL',
            harga_jual = ?,
            keuntungan = ?,
            margin = ?,
            pembayaran = ?,
            tanggal_jual = ?,
            tanggal = ?
        WHERE id = ?
    ''', (harga_jual, untung, margin, pembayaran.strip().upper(), tgl_jual, tgl_jual, item_id))
    conn.commit()
    conn.close()
    item["harga_jual"] = harga_jual
    item["keuntungan"] = untung
    item["margin"] = margin
    item["pembayaran_jual"] = pembayaran
    return item

def get_summary_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT 
            COUNT(*) as total_tx,
            COALESCE(SUM(harga_beli), 0) as total_beli,
            COALESCE(SUM(harga_jual), 0) as total_jual,
            COALESCE(SUM(keuntungan), 0) as total_untung,
            COALESCE(AVG(margin), 0) as avg_margin
        FROM penjualan
        WHERE status = 'TERJUAL'
    ''')
    s = c.fetchone()
    c.execute("SELECT COUNT(*), COALESCE(SUM(harga_beli), 0) FROM penjualan WHERE status = 'READY'")
    r = c.fetchone()
    conn.close()
    return {
        "terjual_count": s[0],
        "total_beli": s[1],
        "total_jual": s[2],
        "total_untung": s[3],
        "avg_margin": s[4],
        "ready_count": r[0],
        "modal_tertahan": r[1]
    }

# --- INTERACTIVE TELEGRAM FLOW ---

def show_main_menu(bot_token, chat_id):
    user_sessions.pop(chat_id, None)
    text = (
        "📱 *GadgetFlow — Sistem Pencatatan HP* ✨\n\n"
        "Silakan pilih aksi yang ingin dilakukan:"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📦 Input Stok Baru (Beli HP)", "callback_data": "start_buy"},
                {"text": "🤝 Jual Stok Ready", "callback_data": "start_sell"}
            ],
            [
                {"text": "📋 Cek Stok Ready", "callback_data": "check_ready"},
                {"text": "📊 Rekap Cuan & Omset", "callback_data": "check_cuan"}
            ],
            [
                {"text": "⚖️ Cek Pajak UMKM (PP 55)", "callback_data": "check_tax"},
                {"text": "📜 10 Penjualan Terakhir", "callback_data": "check_history"}
            ],
            [
                {"text": "📺 Remote TV Xiaomi (Web / Chat)", "callback_data": "show_remote"}
            ]
        ]
    }
    send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

def handle_buy_start(bot_token, chat_id, message_id=None):
    user_sessions[chat_id] = {"step": "WAIT_BRAND", "data": {}}
    text = "📦 *LANGKAH 1/4: PILIH MERK HP*\n\nSilakan pilih merk smartphone yang baru dibeli:"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🍏 Apple", "callback_data": "brand:APPLE"},
                {"text": "🟡 Poco", "callback_data": "brand:POCO"}
            ],
            [
                {"text": "🔵 Samsung", "callback_data": "brand:SAMSUNG"},
                {"text": "🟠 Infinix", "callback_data": "brand:INFINIX"}
            ],
            [
                {"text": "🔴 itel", "callback_data": "brand:ITEL"},
                {"text": "⚪ Xiaomi / Redmi", "callback_data": "brand:XIAOMI"}
            ],
            [
                {"text": "📱 Merk Lainnya", "callback_data": "brand:LAINNYA"},
                {"text": "❌ Batal", "callback_data": "cancel"}
            ]
        ]
    }
    if message_id:
        edit_message(bot_token, chat_id, message_id, text, reply_markup=keyboard)
    else:
        send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

def handle_brand_selected(bot_token, chat_id, brand, message_id):
    user_sessions[chat_id] = {"step": "WAIT_TYPE", "data": {"merk": brand}}
    popular = POPULAR_SERIES.get(brand, [])
    
    text = f"📱 *LANGKAH 2/4: TIPE {brand}*\n\nPilih dari tipe populer di bawah, atau *ketik langsung nama serinya di chat*:\n_(Contoh: {brand} 15 Pink 128GB)_"
    
    buttons = []
    row = []
    for p in popular[:6]:
        row.append({"text": p, "callback_data": f"type:{p}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([
        {"text": "✍️ Ketik Manual di Chat", "callback_data": "type_manual"},
        {"text": "❌ Batal", "callback_data": "cancel"}
    ])

    edit_message(bot_token, chat_id, message_id, text, reply_markup={"inline_keyboard": buttons})

def prompt_buy_price(bot_token, chat_id, type_name):
    session = user_sessions.get(chat_id, {})
    session["data"]["nama_produk"] = type_name
    session["step"] = "WAIT_BUY_PRICE"
    user_sessions[chat_id] = session

    text = (
        f"💵 *LANGKAH 3/4: MODAL BELI*\n\n"
        f"Unit: *{type_name}*\n\n"
        f"Ketik *harga modal beli / kulakan* di chat:\n"
        f"👉 _Contoh: `9.7jt`, `9.700.000`, atau `9700000`_"
    )
    send_tg_message(bot_token, chat_id, text)

def prompt_buy_payment(bot_token, chat_id):
    session = user_sessions.get(chat_id, {})
    session["step"] = "WAIT_BUY_PAY"
    user_sessions[chat_id] = session

    text = "💳 *LANGKAH 4/4: METODE PEMBAYARAN*\n\nPilih metode pembayaran yang dipakai saat kulakan unit ini:"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "BCA", "callback_data": "buy_pay:BCA"},
                {"text": "CC TOPED", "callback_data": "buy_pay:CC TOPED"}
            ],
            [
                {"text": "QRIS", "callback_data": "buy_pay:QRIS"},
                {"text": "CC BRI", "callback_data": "buy_pay:CC BRI"}
            ],
            [
                {"text": "💵 CASH / TUNAI", "callback_data": "buy_pay:CASH"},
                {"text": "TRANSFER LAIN", "callback_data": "buy_pay:TRANSFER"}
            ]
        ]
    }
    send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

def finish_buy(bot_token, chat_id, payment):
    session = user_sessions.get(chat_id, {})
    data = session.get("data", {})
    merk = data.get("merk", "APPLE")
    nama = data.get("nama_produk", "SMARTPHONE")
    beli = data.get("harga_beli", 0)

    new_id = add_ready_stock(merk, nama, beli, payment)
    user_sessions.pop(chat_id, None)

    text = (
        "✅ *UNIT BERHASIL MASUK STOK READY!* 📦🎉\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔖 *ID Ref:* `#{new_id}`\n"
        f"📱 *Merk & Tipe:* *{merk} {nama}*\n"
        f"🔴 *Modal Beli:* *{format_rupiah(beli)}*\n"
        f"💳 *Metode Beli:* {payment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Status: 🟢 *READY (Belum Laku)*\n\n"
        "🚀 _Nanti kalau unit ini laku, cukup klik tombol di bawah untuk catat harga jualnya!_"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"🤝 Jual Unit #{new_id} Sekarang", "callback_data": f"sell_item:{new_id}"}
            ],
            [
                {"text": "📦 Input Unit Lain", "callback_data": "start_buy"},
                {"text": "🏠 Menu Utama", "callback_data": "main_menu"}
            ]
        ]
    }
    send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

# --- SELL READY STOCK FLOW ---

def handle_sell_start(bot_token, chat_id, message_id=None):
    ready_items = get_ready_stocks(10)
    if not ready_items:
        text = (
            "📦 *Stok Ready Masih Kosong*\n\n"
            "Belum ada unit HP di etalase yang berstatus ready.\n"
            "Silakan tambahkan stok dulu dengan klik tombol di bawah:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "📦 + Input Stok Baru", "callback_data": "start_buy"}],
                [{"text": "🏠 Menu Utama", "callback_data": "main_menu"}]
            ]
        }
        if message_id:
            edit_message(bot_token, chat_id, message_id, text, reply_markup=keyboard)
        else:
            send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)
        return

    text = "🤝 *PILIH UNIT YANG SUDAH LAKU:*\n\nPilih transaksi unit yang terjual untuk mencatat harga jualnya:"
    buttons = []
    for item in ready_items:
        btn_text = f"#{item['id']} {item['nama_produk']} (Modal {format_rupiah(item['harga_beli'])})"
        buttons.append([{"text": btn_text, "callback_data": f"sell_item:{item['id']}"}])
    
    buttons.append([{"text": "❌ Batal", "callback_data": "cancel"}])

    if message_id:
        edit_message(bot_token, chat_id, message_id, text, reply_markup={"inline_keyboard": buttons})
    else:
        send_tg_message(bot_token, chat_id, text, reply_markup={"inline_keyboard": buttons})

def prompt_sell_price(bot_token, chat_id, item_id, message_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM penjualan WHERE id = ?", (item_id,))
    item = dict(c.fetchone())
    conn.close()

    user_sessions[chat_id] = {
        "step": "WAIT_SELL_PRICE",
        "data": {
            "id": item_id,
            "nama_produk": item["nama_produk"],
            "harga_beli": item["harga_beli"]
        }
    }

    text = (
        f"💰 *CATAT HARGA JUAL*\n\n"
        f"Unit: *{item['nama_produk']}* (`#{item_id}`)\n"
        f"Modal Beli: *{format_rupiah(item['harga_beli'])})*\n\n"
        f"Ketik *harga jual deal ke pembeli*:\n"
        f"👉 _Contoh: `10.5jt`, `10500000`_"
    )
    send_tg_message(bot_token, chat_id, text)

def prompt_sell_payment(bot_token, chat_id):
    session = user_sessions.get(chat_id, {})
    session["step"] = "WAIT_SELL_PAY"
    user_sessions[chat_id] = session

    text = "💳 *METODE TERIMA PEMBAYARAN*\n\nPilih metode pembayaran dari pembeli:"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "BCA", "callback_data": "sell_pay:BCA"},
                {"text": "CC TOPED", "callback_data": "sell_pay:CC TOPED"}
            ],
            [
                {"text": "QRIS", "callback_data": "sell_pay:QRIS"},
                {"text": "CC BRI", "callback_data": "sell_pay:CC BRI"}
            ],
            [
                {"text": "💵 CASH / TUNAI", "callback_data": "sell_pay:CASH"},
                {"text": "TRANSFER LAIN", "callback_data": "sell_pay:TRANSFER"}
            ]
        ]
    }
    send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

def finish_sell(bot_token, chat_id, payment):
    session = user_sessions.get(chat_id, {})
    data = session.get("data", {})
    item_id = data.get("id")
    harga_jual = data.get("harga_jual", 0)

    sold_item = sell_ready_stock(item_id, harga_jual, payment)
    user_sessions.pop(chat_id, None)

    if not sold_item:
        send_tg_message(bot_token, chat_id, "❌ Gagal memproses penjualan.")
        return

    untung = sold_item["keuntungan"]
    margin = sold_item["margin"]
    sign = "+" if untung >= 0 else "-"

    text = (
        "🎉 *ALHAMDULILLAH, UNIT TERJUAL!* 💰✨\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📱 *Produk:* *{sold_item['nama_produk']}* (`#{item_id}`)\n"
        f"🔴 *Modal Beli:* {format_rupiah(sold_item['harga_beli'])}\n"
        f"🟢 *Harga Jual:* *{format_rupiah(sold_item['harga_jual'])}*\n"
        f"💳 *Metode Terima:* {payment}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Cuan Bersih:* *{sign}{format_rupiah(abs(untung))}*\n"
        f"📈 *Margin Profit:* *{margin*100:.2f}%*\n\n"
        "🚀 _Data penjualan otomatis masuk ke Web Dashboard GadgetFlow!_"
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": "🤝 Jual Unit Lainnya", "callback_data": "start_sell"}],
            [{"text": "📊 Lihat Rekap Cuan", "callback_data": "check_cuan"}],
            [{"text": "🏠 Menu Utama", "callback_data": "main_menu"}]
        ]
    }
    send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

# --- CALLBACK QUERY ROUTER ---

def handle_callback_query(bot_token, cq):
    cb_id = cq["id"]
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    data = cq.get("data", "")
    answer_callback(bot_token, cb_id)

    if data == "main_menu" or data == "cancel":
        show_main_menu(bot_token, chat_id)
        return

    if data == "start_buy":
        handle_buy_start(bot_token, chat_id, msg_id)
        return

    if data.startswith("brand:"):
        brand = data.split(":", 1)[1]
        handle_brand_selected(bot_token, chat_id, brand, msg_id)
        return

    if data.startswith("type:"):
        type_name = data.split(":", 1)[1]
        prompt_buy_price(bot_token, chat_id, type_name)
        return

    if data == "type_manual":
        session = user_sessions.get(chat_id, {})
        session["step"] = "WAIT_MANUAL_TYPE"
        user_sessions[chat_id] = session
        send_tg_message(bot_token, chat_id, "✍️ Silakan ketik *nama seri/tipe lengkap smartphone* di chat:")
        return

    if data.startswith("buy_pay:"):
        pay = data.split(":", 1)[1]
        finish_buy(bot_token, chat_id, pay)
        return

    if data == "start_sell":
        handle_sell_start(bot_token, chat_id, msg_id)
        return

    if data.startswith("sell_item:"):
        item_id = int(data.split(":", 1)[1])
        prompt_sell_price(bot_token, chat_id, item_id, msg_id)
        return

    if data.startswith("sell_pay:"):
        pay = data.split(":", 1)[1]
        finish_sell(bot_token, chat_id, pay)
        return

    if data == "check_ready":
        items = get_ready_stocks(10)
        if not items:
            send_tg_message(bot_token, chat_id, "📦 Belum ada unit di stok ready.")
            return
        send_tg_message(bot_token, chat_id, "📦 *DAFTAR STOK READY (BELUM LAKU):*\n━━━━━━━━━━━━━━━━━━")
        for it in items:
            it_text = f"📱 *{it['nama_produk']}* (`#{it['id']}`)\n🔴 Modal: *{format_rupiah(it['harga_beli'])}* | Bayar: {it['pembayaran']}"
            it_kb = {
                "inline_keyboard": [
                    [
                        {"text": "🤝 Jual Unit", "callback_data": f"sell_item:{it['id']}"},
                        {"text": "✏️ Edit", "callback_data": f"edit_menu:{it['id']}"},
                        {"text": "🗑️ Hapus", "callback_data": f"del_item:{it['id']}"}
                    ]
                ]
            }
            send_tg_message(bot_token, chat_id, it_text, reply_markup=it_kb)
        return

    if data.startswith("del_item:"):
        item_id = int(data.split(":", 1)[1])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM penjualan WHERE id = ? AND status = 'READY'", (item_id,))
        c.commit()
        conn.close()
        send_tg_message(bot_token, chat_id, f"🗑️ Unit stok `#{item_id}` berhasil dihapus!")
        return

    if data.startswith("edit_menu:"):
        item_id = int(data.split(":", 1)[1])
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM penjualan WHERE id = ?", (item_id,))
        item = dict(c.fetchone())
        conn.close()

        text = f"✏️ *EDIT STOK UNIT #{item_id}*\n\nUnit: *{item['nama_produk']}*\nModal saat ini: *{format_rupiah(item['harga_beli'])}*\n\nPilih bagian yang mau kamu ubah:"
        keyboard = {
            "inline_keyboard": [
                [{"text": "💰 Ubah Harga Modal", "callback_data": f"edit_cost:{item_id}"}],
                [{"text": "📱 Ubah Nama / Tipe HP", "callback_data": f"edit_title:{item_id}"}],
                [{"text": "❌ Batal", "callback_data": "check_ready"}]
            ]
        }
        send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)
        return

    if data.startswith("edit_cost:"):
        item_id = int(data.split(":", 1)[1])
        user_sessions[chat_id] = {"step": "WAIT_EDIT_COST", "data": {"id": item_id}}
        send_tg_message(bot_token, chat_id, f"💰 Ketik *harga modal baru* untuk unit `#{item_id}` di chat:\n_(Contoh: `9.5jt` atau `9500000`)_")
        return

    if data.startswith("edit_title:"):
        item_id = int(data.split(":", 1)[1])
        user_sessions[chat_id] = {"step": "WAIT_EDIT_TITLE", "data": {"id": item_id}}
        send_tg_message(bot_token, chat_id, f"📱 Ketik *nama / tipe HP baru* untuk unit `#{item_id}` di chat:\n_(Contoh: ITEL A100CS 4/64 HITAM)_")
        return

    if data == "check_cuan":
        s = get_summary_stats()
        text = (
            "📊 *REKAP KEUANGAN GADGETFLOW*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🛒 Total Laku: *{s['terjual_count']} unit*\n"
            f"🟢 Total Penjualan: *{format_rupiah(s['total_jual'])}*\n"
            f"🔴 Total Modal Terjual: *{format_rupiah(s['total_beli'])}*\n"
            f"💰 *Total Cuan Bersih: +{format_rupiah(s['total_untung'])}*\n"
            f"📈 Rata-rata Margin: *{s['avg_margin']*100:.2f}%*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📦 Unit Ready: *{s['ready_count']} unit*\n"
            f"⏳ Modal Tertahan: *{format_rupiah(s['modal_tertahan'])}*\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        send_tg_message(bot_token, chat_id, text)
        return

    if data == "check_tax":
        s = get_summary_stats()
        tot_omset = s['total_jual']
        free_limit = 500_000_000.0
        pkp_limit = 4_800_000_000.0

        if tot_omset <= free_limit:
            taxable = 0.0
            tax = 0.0
            status = "🟢 BEBAS PAJAK (Nihil)"
            keterangan = f"Omset belum lewat batas 500 Juta. Sisa kuota bebas pajak: *{format_rupiah(free_limit - tot_omset)}*."
        elif tot_omset <= pkp_limit:
            taxable = tot_omset - free_limit
            tax = taxable * 0.005 # 0.5%
            status = "🟡 PPh Final UMKM 0,5% (PP 55/2022)"
            keterangan = f"Kelebihan omset di atas 500 Jt dikenakan tarif flat 0,5%."
        else:
            taxable = tot_omset - free_limit
            tax = taxable * 0.005
            status = "🔴 Wajib PKP (Omset > 4,8 Miliar)"
            keterangan = f"Omset melewati batas UMKM 4,8 Miliar. Wajib lapor PKP & PPN."

        pct_pkp = min(100.0, (tot_omset / pkp_limit) * 100.0)

        text = (
            "⚖️ *STATUS & TRACKER PAJAK UMKM*\n"
            "_(Dasar Hukum: PP 55 / 2022 & UU HPP)_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📌 Status: *{status}*\n"
            f"🛒 Total Omset Penjualan: *{format_rupiah(tot_omset)}*\n"
            f"🛡️ Batas Bebas Pajak: *Rp 500.000.000*\n"
            f"📋 Omset Kena Pajak (DPP): *{format_rupiah(taxable)}*\n"
            "──────────────────\n"
            f"💵 *Estimasi Pajak Terutang (0,5%): {format_rupiah(tax)}*\n"
            "──────────────────\n"
            f"📈 Progress Menuju 4,8 Miliar: *{pct_pkp:.1f}%*\n"
            f"💡 _{keterangan}_\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        send_tg_message(bot_token, chat_id, text)
        return

    if data == "check_history":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM penjualan WHERE status = 'TERJUAL' ORDER BY id DESC LIMIT 10")
        rows = [dict(r) for r in c.fetchall()]
        conn.close()

        if not rows:
            send_tg_message(bot_token, chat_id, "Belum ada riwayat penjualan.")
            return

        lines = ["📜 *10 PENJUALAN TERAKHIR:*", "━━━━━━━━━━━━━━━━━━"]
        for r in rows:
            unt = r["keuntungan"]
            lines.append(
                f"• *{r['nama_produk']}* (`#{r['id']}`)\n"
                f"  Beli: {format_rupiah(r['harga_beli'])} ➔ Jual: {format_rupiah(r['harga_jual'])}\n"
                f"  💰 *Cuan: +{format_rupiah(unt)}* ({r['margin']*100:.1f}%) · {r['pembayaran']}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━\n_Data lengkap 148+ transaksi ada di Web Dashboard._")
        send_tg_message(bot_token, chat_id, "\n\n".join(lines))
        return

    if data == "show_remote":
        send_remote_interface(bot_token, chat_id)
        return

    if data.startswith("tv_key:"):
        key_name = data.split(":")[1]
        try:
            httpx.post("http://127.0.0.1:8050/api/key", json={"key": key_name}, timeout=1.5)
        except Exception:
            pass
        return

    if data.startswith("tv_app:"):
        app_name = data.split(":")[1]
        try:
            httpx.post("http://127.0.0.1:8050/api/app", json={"package": app_name}, timeout=1.5)
        except Exception:
            pass
        return

def send_remote_interface(bot_token, chat_id, message_id=None):
    text = (
        "📺 *MiRemote — Xiaomi TV Controller* ✨\n"
        "Model: `MiTV-AXFU0` (IP: `192.168.1.19`)\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📱 *Buka Web Remote Lengkap di Browser HP / iPad:*\n"
        "👉 http://192.168.1.8:8050\n"
        "_(Tampilan remote fisik, haptic getar, & ketik keyboard)_\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Atau pencet langsung dari tombol chat di bawah:"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "▲ Atas", "callback_data": "tv_key:up"}
            ],
            [
                {"text": "◀ Kiri", "callback_data": "tv_key:left"},
                {"text": "🔘 OK", "callback_data": "tv_key:ok"},
                {"text": "▶ Kanan", "callback_data": "tv_key:right"}
            ],
            [
                {"text": "▼ Bawah", "callback_data": "tv_key:down"}
            ],
            [
                {"text": "↩ Kembali", "callback_data": "tv_key:back"},
                {"text": "🏠 Home", "callback_data": "tv_key:home"},
                {"text": "☰ Menu", "callback_data": "tv_key:menu"}
            ],
            [
                {"text": "🔉 Vol -", "callback_data": "tv_key:voldown"},
                {"text": "🔇 Mute", "callback_data": "tv_key:mute"},
                {"text": "🔊 Vol +", "callback_data": "tv_key:volup"}
            ],
            [
                {"text": "▶️ YouTube", "callback_data": "tv_app:youtube"},
                {"text": "📺 Live TV", "callback_data": "tv_app:livetv"},
                {"text": "⏻ Power", "callback_data": "tv_key:power"}
            ],
            [
                {"text": "« Kembali ke Menu Utama", "callback_data": "main_menu"}
            ]
        ]
    }
    if message_id:
        edit_message(bot_token, chat_id, message_id, text, reply_markup=keyboard)
    else:
        send_tg_message(bot_token, chat_id, text, reply_markup=keyboard)

# --- MESSAGE HANDLER (TEXT & NATURAL CHAT) ---

def handle_text_message(bot_token, chat_id, text):
    t = text.strip()
    low = t.lower()

    if low in ("/start", "/menu", "menu", "start"):
        show_main_menu(bot_token, chat_id)
        return

    if low in ("/beli", "beli", "tambah", "stok"):
        handle_buy_start(bot_token, chat_id)
        return

    if low in ("/jual", "jual", "laku"):
        handle_sell_start(bot_token, chat_id)
        return

    if low in ("/pajak", "pajak", "tax"):
        s = get_summary_stats()
        tot_omset = s['total_jual']
        free_limit = 500_000_000.0
        pkp_limit = 4_800_000_000.0
        if tot_omset <= free_limit:
            taxable = 0.0
            tax = 0.0
            status = "🟢 BEBAS PAJAK (Nihil)"
            keterangan = f"Omset belum lewat batas 500 Juta. Sisa kuota bebas pajak: *{format_rupiah(free_limit - tot_omset)}*."
        elif tot_omset <= pkp_limit:
            taxable = tot_omset - free_limit
            tax = taxable * 0.005 # 0.5%
            status = "🟡 PPh Final UMKM 0,5% (PP 55/2022)"
            keterangan = f"Kelebihan omset di atas 500 Jt dikenakan tarif flat 0,5%."
        else:
            taxable = tot_omset - free_limit
            tax = taxable * 0.005
            status = "🔴 Wajib PKP (Omset > 4,8 Miliar)"
            keterangan = f"Omset melewati batas UMKM 4,8 Miliar. Wajib lapor PKP & PPN."
        pct_pkp = min(100.0, (tot_omset / pkp_limit) * 100.0)
        text_reply = (
            "⚖️ *STATUS & TRACKER PAJAK UMKM*\n"
            "_(Dasar Hukum: PP 55 / 2022 & UU HPP)_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📌 Status: *{status}*\n"
            f"🛒 Total Omset Penjualan: *{format_rupiah(tot_omset)}*\n"
            f"🛡️ Batas Bebas Pajak: *Rp 500.000.000*\n"
            f"📋 Omset Kena Pajak (DPP): *{format_rupiah(taxable)}*\n"
            "──────────────────\n"
            f"💵 *Estimasi Pajak Terutang (0,5%): {format_rupiah(tax)}*\n"
            "──────────────────\n"
            f"📈 Progress Menuju 4,8 Miliar: *{pct_pkp:.1f}%*\n"
            f"💡 _{keterangan}_\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        send_tg_message(bot_token, chat_id, text_reply)
        return

    if low in ("/cuan", "cuan", "rekap"):
        s = get_summary_stats()
        text_reply = (
            "📊 *REKAP KEUANGAN GADGETFLOW*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🛒 Total Laku: *{s['terjual_count']} unit*\n"
            f"🟢 Total Penjualan: *{format_rupiah(s['total_jual'])}*\n"
            f"🔴 Total Modal Terjual: *{format_rupiah(s['total_beli'])}*\n"
            f"💰 *Total Cuan Bersih: +{format_rupiah(s['total_untung'])}*\n"
            f"📈 Rata-rata Margin: *{s['avg_margin']*100:.2f}%*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📦 Unit Ready: *{s['ready_count']} unit*\n"
            f"⏳ Modal Tertahan: *{format_rupiah(s['modal_tertahan'])}*\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        send_tg_message(bot_token, chat_id, text_reply)
        return

    if low in ("/terakhir", "terakhir", "history", "/history"):
        handle_callback_query(bot_token, {"id": "0", "message": {"chat": {"id": chat_id}, "message_id": 0}, "data": "check_history"})
        return

    if low in ("/server", "server", "/baterai", "baterai", "/status", "status"):
        try:
            r = httpx.get("http://127.0.0.1:9090/api/telemetry", timeout=3)
            if r.status_code == 200:
                d = r.json()
                b = d["battery"]
                c = d["cpu"]
                m = d["memory"]
                dk = d["disk"]
                w = d["wifi"]
                bat_icon = "⚡" if b["ac_online"] else "🔋"
                status_txt = (
                    f"💻 *STATUS SERVER LAPTOP ({d['hostname'].upper()})*\n"
                    f"Model: {d['model']}\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"{bat_icon} *Baterai:* {b['capacity']}% ({b['status']})\n"
                    f"⚡ *Daya:* {b['power_w']} W · Sisa: {b['time_left']}\n"
                    f"🌡️ *Suhu CPU:* {c['temp']}°C · Beban: {c['percent']}%\n"
                    f"🧠 *RAM:* {m['used_gb']} / {m['total_gb']} GB ({m['percent']}%)\n"
                    f"💾 *SSD:* {dk['used_gb']} / {dk['total_gb']} GB ({dk['percent']}%) [Fisik: {dk.get('physical_gb', 256)} GB]\n"
                    f"📶 *Wi-Fi:* {w['ssid']} ({w['signal']}%) · {w['ip']}\n"
                    f"⏱️ *Uptime:* {d['uptime']}\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🌐 _Dashboard: http://{w['ip']}:9090_"
                )
                send_tg_message(bot_token, chat_id, status_txt)
                return
        except Exception as e:
            send_tg_message(bot_token, chat_id, "⚠️ Gagal mengambil telemetry server.")
            return

    if low in ("/remote", "remote", "/tv", "tv"):
        send_remote_interface(bot_token, chat_id)
        return

    # Check active state
    session = user_sessions.get(chat_id)
    if session:
        step = session.get("step")

        if step in ("WAIT_TYPE", "WAIT_MANUAL_TYPE"):
            brand = session.get("data", {}).get("merk", "")
            type_text = t.strip().upper()
            if brand and brand != "LAINNYA" and not type_text.startswith(brand):
                full_product_name = f"{brand} {type_text}"
            else:
                full_product_name = type_text
            prompt_buy_price(bot_token, chat_id, full_product_name)
            return

        if step == "WAIT_BUY_PRICE":
            val = parse_nominal(t)
            if not val or val < 10000:
                send_tg_message(bot_token, chat_id, "⚠️ Nominal belum sesuai. Silakan ketik angka modal (contoh: `9.7jt` atau `9700000`):")
                return
            session["data"]["harga_beli"] = val
            prompt_buy_payment(bot_token, chat_id)
            return

        if step == "WAIT_SELL_PRICE":
            val = parse_nominal(t)
            if not val or val < 10000:
                send_tg_message(bot_token, chat_id, "⚠️ Nominal belum sesuai. Silakan ketik angka harga jual (contoh: `10.5jt` atau `10500000`):")
                return
            session["data"]["harga_jual"] = val
            prompt_sell_payment(bot_token, chat_id)
            return

        if step == "WAIT_EDIT_COST":
            val = parse_nominal(t)
            if not val or val < 10000:
                send_tg_message(bot_token, chat_id, "⚠️ Nominal belum sesuai. Silakan ketik angka harga modal (contoh: `9.5jt` atau `9500000`):")
                return
            item_id = session.get("data", {}).get("id")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE penjualan SET harga_beli = ? WHERE id = ?", (val, item_id))
            conn.commit()
            conn.close()
            user_sessions.pop(chat_id, None)
            send_tg_message(bot_token, chat_id, f"✅ *Modal unit `#{item_id}` berhasil diubah menjadi: {format_rupiah(val)}*")
            return

        if step == "WAIT_EDIT_TITLE":
            new_title = t.strip().upper()
            item_id = session.get("data", {}).get("id")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE penjualan SET nama_produk = ? WHERE id = ?", (new_title, item_id))
            conn.commit()
            conn.close()
            user_sessions.pop(chat_id, None)
            send_tg_message(bot_token, chat_id, f"✅ *Tipe HP unit `#{item_id}` berhasil diubah menjadi: {new_title}*")
            return

    # Fallback: Quick direct text format
    # e.g. "IPHONE 15 PINK beli 9.7jt jual 10.5jt bca"
    beli_match = re.search(r'beli\s*[:=]?\s*([0-9.,]+(?:\s*(?:jt|juta|k|rb|ribu))?)', t, re.I)
    jual_match = re.search(r'jual\s*[:=]?\s*([0-9.,]+(?:\s*(?:jt|juta|k|rb|ribu))?)', t, re.I)
    if beli_match and jual_match:
        b_val = parse_nominal(beli_match.group(1))
        j_val = parse_nominal(jual_match.group(1))
        clean_name = re.sub(r'\b(beli|jual|[:=]|bca|bri|bni|qris|cc\s*toped|cash|transfer)\b.*', '', t, flags=re.I).strip().upper()
        if not clean_name:
            clean_name = "SMARTPHONE"
        
        # detect payment
        pay = "BCA"
        pay_match = re.search(r'\b(cc\s*toped|cc\s*bri|cc\s*bni|bca|bri|bni|qris|cash|transfer)\b', t, re.I)
        if pay_match:
            pay = pay_match.group(1).upper()
        
        # insert ready and immediately sell
        item_id = add_ready_stock("GADGET", clean_name, b_val, pay)
        sold = sell_ready_stock(item_id, j_val, pay)
        send_tg_message(bot_token, chat_id, f"✅ Penjualan langsung tercatat! Cuan: +{format_rupiah(sold['keuntungan'])} ({sold['margin']*100:.2f}%)")
        return

    # Fallback: Smart direct phone name detection even without menu clicks
    # (e.g. user just types "A100Cs 4/64 HITAM" or "iPhone 13 128gb")
    detected_brand = "LAINNYA"
    for b in ("APPLE", "IPHONE", "POCO", "SAMSUNG", "GALAXY", "INFINIX", "ITEL", "XIAOMI", "REDMI"):
        if b in t.upper():
            detected_brand = "APPLE" if b in ("APPLE", "IPHONE") else ("XIAOMI" if b in ("XIAOMI", "REDMI") else ("SAMSUNG" if b == "GALAXY" else b))
            break
    
    has_spec = re.search(r'\b(\d+\/\d+|\d+\s*gb|hitam|putih|pink|blue|black|gold|pro|max|plus)\b', t, re.I)
    
    if (detected_brand != "LAINNYA" or has_spec) and len(t) >= 4 and not t.startswith("/"):
        full_product_name = t.strip().upper()
        user_sessions[chat_id] = {
            "step": "WAIT_BUY_PRICE",
            "data": {
                "merk": detected_brand,
                "nama_produk": full_product_name
            }
        }
        text_prompt = (
            f"📱 *Unit Terdeteksi:* *{full_product_name}*\n"
            f"Merk: *{detected_brand}*\n\n"
            f"💵 *Langkah Selanjutnya: Masukkan Harga Modal Beli*:\n"
            f"👉 _Contoh: `9.7jt`, `9.700.000`, atau `9700000`_"
        )
        send_tg_message(bot_token, chat_id, text_prompt)
        return

    show_main_menu(bot_token, chat_id)

def main():
    token = get_token()
    if not token:
        print("ERROR: Bot token belum diset!")
        print("Silakan masukkan token di file .bot_token atau export TELEGRAM_BOT_TOKEN='...'")
        sys.exit(1)

    print(f"[{datetime.datetime.now()}] GadgetFlow Interactive Bot aktif & mendengarkan (Turbo Engine)...")
    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"

    # Pre-warm outgoing connection pool
    get_api_client()

    # Dedicated long-polling client with keep-alive
    poll_limits = httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=60.0)
    poll_timeout = httpx.Timeout(connect=10.0, read=35.0, write=10.0, pool=35.0)
    poll_client = httpx.Client(timeout=poll_timeout, limits=poll_limits)

    while True:
        try:
            resp = poll_client.get(
                poll_url,
                params={
                    "offset": offset,
                    "timeout": 20,
                    "allowed_updates": ["message", "callback_query"]
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    # 1. Callback Query (Tombol diklik)
                    if "callback_query" in update:
                        handle_callback_query(token, update["callback_query"])
                    
                    # 2. Text Message
                    elif "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        print(f"Pesan dari {chat_id}: {text}")
                        handle_text_message(token, chat_id, text)
            elif resp.status_code == 409:
                print("Conflict: another bot instance is running. Waiting 5s...")
                time.sleep(5)
            else:
                time.sleep(1)
        except (httpx.ReadTimeout, httpx.WriteTimeout):
            # Normal long-polling timeout when no new messages arrived, re-poll instantly
            continue
        except (httpx.ConnectTimeout, httpx.NetworkError) as e:
            print("Connection hiccup, retrying in 1s:", e)
            time.sleep(1)
        except Exception as e:
            print("Polling error:", e)
            time.sleep(1)

if __name__ == "__main__":
    main()
