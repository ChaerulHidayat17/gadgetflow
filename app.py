import os
import sqlite3
import datetime
from typing import Optional
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.sqlite")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI(title="GadgetFlow — Platform Penjualan & Stok HP")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS penjualan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tanggal TEXT,
        nama_produk TEXT NOT NULL,
        merk TEXT DEFAULT 'APPLE',
        qty INTEGER DEFAULT 1,
        harga_beli REAL NOT NULL,
        harga_jual REAL DEFAULT 0,
        pembayaran TEXT DEFAULT 'CASH',
        keuntungan REAL DEFAULT 0,
        margin REAL DEFAULT 0,
        status TEXT DEFAULT 'TERJUAL',
        tanggal_beli TEXT,
        tanggal_jual TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

init_db()

class BuyCreate(BaseModel):
    nama_produk: str
    merk: Optional[str] = "APPLE"
    harga_beli: float
    pembayaran: Optional[str] = "CASH"
    qty: Optional[int] = 1
    tanggal: Optional[str] = None

class SellAction(BaseModel):
    id: int
    harga_jual: float
    pembayaran: Optional[str] = "BCA"
    tanggal_jual: Optional[str] = None

class StockUpdate(BaseModel):
    id: int
    nama_produk: str
    merk: Optional[str] = "APPLE"
    harga_beli: float
    pembayaran: Optional[str] = "CASH"
    tanggal_beli: Optional[str] = None

def calculate_tax(omset: float):
    # UU HPP & PP 55/2022 untuk UMKM Orang Pribadi
    # Batas PTKP Omset: Rp 500.000.000
    # Tarif PPh Final: 0.5% dari kelebihan omset (di bawah Rp 4.8 Miliar)
    free_limit = 500_000_000.0
    pkp_limit = 4_800_000_000.0
    
    if omset <= free_limit:
        taxable_omset = 0.0
        tax_amount = 0.0
        status = "BEBAS PAJAK (Nihil)"
        status_color = "emerald"
    elif omset <= pkp_limit:
        taxable_omset = omset - free_limit
        tax_amount = taxable_omset * 0.005 # 0.5%
        status = "PPh Final UMKM 0.5%"
        status_color = "amber"
    else:
        taxable_omset = omset - free_limit
        tax_amount = taxable_omset * 0.005 # Baseline UMKM + Wajib PKP
        status = "Wajib PKP (Lewat 4.8 Miliar)"
        status_color = "rose"

    pct_to_free = min(100.0, (omset / free_limit) * 100.0) if free_limit > 0 else 100.0
    pct_to_pkp = min(100.0, (omset / pkp_limit) * 100.0) if pkp_limit > 0 else 100.0
    
    return {
        "omset": omset,
        "free_limit": free_limit,
        "pkp_limit": pkp_limit,
        "taxable_omset": taxable_omset,
        "tax_amount": tax_amount,
        "status": status,
        "status_color": status_color,
        "pct_to_free": pct_to_free,
        "pct_to_pkp": pct_to_pkp
    }

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    conn = get_db()
    c = conn.cursor()
    
    # 1. Summary of Completed Sales
    c.execute('''
        SELECT 
            COUNT(*) as total_tx,
            COALESCE(SUM(qty), 0) as total_units_sold,
            COALESCE(SUM(harga_beli), 0) as total_beli_terjual,
            COALESCE(SUM(harga_jual), 0) as total_omset,
            COALESCE(SUM(keuntungan), 0) as total_untung,
            COALESCE(AVG(margin), 0) as avg_margin
        FROM penjualan
        WHERE status = 'TERJUAL'
    ''')
    stats = dict(c.fetchone())

    # 2. Summary of Ready Stocks (Modal Tertahan)
    c.execute('''
        SELECT 
            COUNT(*) as ready_count,
            COALESCE(SUM(harga_beli), 0) as modal_tertahan
        FROM penjualan
        WHERE status = 'READY'
    ''')
    ready_summary = dict(c.fetchone())
    stats["ready_count"] = ready_summary["ready_count"]
    stats["modal_tertahan"] = ready_summary["modal_tertahan"]

    # 3. Ready Stock List
    c.execute("SELECT * FROM penjualan WHERE status = 'READY' ORDER BY id DESC")
    ready_stocks = [dict(row) for row in c.fetchall()]

    # 4. Recent Completed Sales (Semua Data Penjualan)
    c.execute("SELECT * FROM penjualan WHERE status = 'TERJUAL' ORDER BY id DESC")
    recent_sales = [dict(row) for row in c.fetchall()]

    # 5. Payment breakdown (Terjual)
    c.execute('''
        SELECT pembayaran, COUNT(*) as count, SUM(keuntungan) as total_profit
        FROM penjualan
        WHERE status = 'TERJUAL'
        GROUP BY pembayaran
        ORDER BY count DESC
    ''')
    payment_stats = [dict(row) for row in c.fetchall()]

    # 6. Top Products by Profit
    c.execute('''
        SELECT nama_produk, COUNT(*) as qty_sold, SUM(keuntungan) as total_profit, SUM(harga_jual) as total_revenue
        FROM penjualan
        WHERE status = 'TERJUAL'
        GROUP BY UPPER(nama_produk)
        ORDER BY total_profit DESC
        LIMIT 6
    ''')
    top_products = [dict(row) for row in c.fetchall()]

    # 7. Tax Estimation Calculator (UU HPP & PP 55/2022)
    tax_info = calculate_tax(stats.get("total_omset", 0))

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "stats": stats,
            "tax_info": tax_info,
            "ready_stocks": ready_stocks,
            "recent_sales": recent_sales,
            "payment_stats": payment_stats,
            "top_products": top_products
        }
    )

@app.get("/api/stats")
async def api_stats():
    conn = get_db()
    c = conn.cursor()

    # Monthly breakdown for chart
    c.execute('''
        SELECT 
            SUBSTR(tanggal_jual, 1, 7) as month,
            COUNT(*) as total_unit,
            SUM(harga_beli) as beli,
            SUM(harga_jual) as jual,
            SUM(keuntungan) as untung
        FROM penjualan
        WHERE status = 'TERJUAL' AND tanggal_jual IS NOT NULL AND tanggal_jual != ''
        GROUP BY month
        ORDER BY month ASC
    ''')
    monthly = [dict(row) for row in c.fetchall()]

    # Payment methods
    c.execute('''
        SELECT pembayaran, COUNT(*) as count, SUM(keuntungan) as total_profit
        FROM penjualan
        WHERE status = 'TERJUAL'
        GROUP BY pembayaran
        ORDER BY count DESC
    ''')
    payments = [dict(row) for row in c.fetchall()]

    # Top products
    c.execute('''
        SELECT UPPER(nama_produk) as product, COUNT(*) as sold, SUM(keuntungan) as profit
        FROM penjualan
        WHERE status = 'TERJUAL'
        GROUP BY UPPER(nama_produk)
        ORDER BY profit DESC
        LIMIT 8
    ''')
    top_prods = [dict(row) for row in c.fetchall()]

    # Ready count and tied modal
    c.execute("SELECT COUNT(*), COALESCE(SUM(harga_beli), 0) FROM penjualan WHERE status = 'READY'")
    r_row = c.fetchone()

    # Total omset for tax
    c.execute("SELECT COALESCE(SUM(harga_jual), 0) FROM penjualan WHERE status = 'TERJUAL'")
    tot_omset = c.fetchone()[0]
    tax_info = calculate_tax(tot_omset)

    conn.close()
    return {
        "monthly": monthly,
        "payments": payments,
        "top_products": top_prods,
        "ready_units": r_row[0],
        "modal_tertahan": r_row[1],
        "tax": tax_info
    }

@app.get("/api/stock/ready")
async def api_get_ready(q: Optional[str] = Query(None)):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM penjualan WHERE status = 'READY'"
    params = []
    if q:
        query += " AND (nama_produk LIKE ? OR merk LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    query += " ORDER BY id DESC"
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@app.post("/api/stock/buy")
async def api_stock_buy(item: BuyCreate):
    tgl = item.tanggal or datetime.date.today().strftime("%Y-%m-%d")
    merk = (item.merk or "APPLE").strip().upper()
    nama = item.nama_produk.strip().upper()
    bayar = (item.pembayaran or "CASH").strip().upper()

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO penjualan (tanggal, nama_produk, merk, qty, harga_beli, harga_jual, pembayaran, keuntungan, margin, status, tanggal_beli)
        VALUES (?, ?, ?, ?, ?, 0, ?, 0, 0, 'READY', ?)
    ''', (tgl, nama, merk, item.qty, item.harga_beli, bayar, tgl))
    new_id = c.lastrowid
    conn.commit()
    c.execute('SELECT * FROM penjualan WHERE id = ?', (new_id,))
    created = dict(c.fetchone())
    conn.close()
    return {"status": "success", "data": created}

@app.post("/api/stock/update")
async def api_stock_update(item: StockUpdate):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM penjualan WHERE id = ?', (item.id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
    
    tgl = item.tanggal_beli or row["tanggal_beli"]
    nama = item.nama_produk.strip().upper()
    merk = (item.merk or row["merk"]).strip().upper()
    bayar = (item.pembayaran or row["pembayaran"]).strip().upper()
    
    c.execute('''
        UPDATE penjualan
        SET nama_produk = ?,
            merk = ?,
            harga_beli = ?,
            pembayaran = ?,
            tanggal_beli = ?,
            tanggal = ?
        WHERE id = ?
    ''', (nama, merk, item.harga_beli, bayar, tgl, tgl, item.id))
    conn.commit()
    c.execute('SELECT * FROM penjualan WHERE id = ?', (item.id,))
    updated = dict(c.fetchone())
    conn.close()
    return {"status": "success", "data": updated}

@app.post("/api/stock/sell")
async def api_stock_sell(action: SellAction):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM penjualan WHERE id = ?', (action.id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
    
    item = dict(row)
    tgl_jual = action.tanggal_jual or datetime.date.today().strftime("%Y-%m-%d")
    untung = (action.harga_jual - item["harga_beli"]) * item["qty"]
    margin = (untung / (action.harga_jual * item["qty"])) if action.harga_jual > 0 else 0
    bayar = (action.pembayaran or "BCA").strip().upper()

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
    ''', (action.harga_jual, untung, margin, bayar, tgl_jual, tgl_jual, action.id))
    conn.commit()
    c.execute('SELECT * FROM penjualan WHERE id = ?', (action.id,))
    updated = dict(c.fetchone())
    conn.close()
    return {"status": "success", "data": updated}

@app.delete("/api/sales/{sale_id}")
async def api_delete_sale(sale_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM penjualan WHERE id = ?', (sale_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
    return {"status": "success", "message": f"Data #{sale_id} berhasil dihapus"}

@app.get("/export/csv")
async def export_csv():
    import io, csv
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, tanggal_jual, merk, nama_produk, qty, harga_beli, harga_jual, keuntungan, margin, pembayaran FROM penjualan WHERE status = 'TERJUAL' ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["No", "Tanggal", "Merk", "Nama Produk", "Qty", "Harga Beli", "Harga Jual", "Keuntungan", "Margin", "Pembayaran"])
    for r in rows:
        margin_pct = f"{r['margin']*100:.2f}%"
        writer.writerow([r['id'], r['tanggal_jual'], r['merk'], r['nama_produk'], r['qty'], int(r['harga_beli']), int(r['harga_jual']), int(r['keuntungan']), margin_pct, r['pembayaran']])

    from fastapi.responses import Response
    return Response(
        content=output.getvalue().encode('utf-8-sig'),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=Buku-Penjualan-GadgetFlow.csv"}
    )
