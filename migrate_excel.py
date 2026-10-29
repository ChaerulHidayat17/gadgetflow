import zipfile
import xml.etree.ElementTree as ET
import sqlite3
import datetime
import os

EXCEL_PATH = '/home/chaerul17/.hermes/cache/documents/native-inputs/83fa17a81a54bd75b29859fbf7fe682ea5b7e6d14c42a00a5cfa8d28ca4bb531/doc_58530212c859_Catatan Keuangan.xlsx'
DB_PATH = '/home/chaerul17/gadgetflow/data.sqlite'

def parse_date(val):
    if not val:
        return datetime.date.today().strftime('%Y-%m-%d')
    try:
        f = float(val)
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(f))
        return d.strftime('%Y-%m-%d')
    except Exception:
        s = str(val).strip()
        if len(s) == 10 and '-' in s:
            parts = s.split('-')
            if len(parts[0]) == 2 and len(parts[2]) == 4: # DD-MM-YYYY
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return s

with zipfile.ZipFile(EXCEL_PATH) as z:
    shared_strings = []
    if 'xl/sharedStrings.xml' in z.namelist():
        sst = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in sst.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
            t = si.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
            if t is not None:
                shared_strings.append(t.text or '')
            else:
                shared_strings.append(''.join(node.text or '' for node in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')))

    def parse_sheet(sheet_xml):
        tree = ET.fromstring(z.read(sheet_xml))
        rows = []
        for row in tree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
            cols = {}
            for c in row.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                r_attr = c.attrib.get('r', '')
                t_attr = c.attrib.get('t', '')
                v_el = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                val = v_el.text if v_el is not None else None
                if t_attr == 's' and val is not None:
                    val = shared_strings[int(val)]
                col_letters = ''.join([ch for ch in r_attr if ch.isalpha()])
                cols[col_letters] = val
            rows.append(cols)
        return rows

    rows = parse_sheet('xl/worksheets/sheet2.xml')

# Connect to sqlite
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS penjualan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal TEXT,
    nama_produk TEXT NOT NULL,
    qty INTEGER DEFAULT 1,
    harga_beli REAL NOT NULL,
    harga_jual REAL NOT NULL,
    pembayaran TEXT,
    keuntungan REAL NOT NULL,
    margin REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')
c.execute('DELETE FROM penjualan')

inserted = 0
for r in rows[1:]:
    prod = r.get('C')
    hb = r.get('E')
    hj = r.get('F')
    if not prod or not hb or not hj:
        continue
    try:
        hb_val = float(hb)
        hj_val = float(hj)
        qty_val = int(float(r.get('D', 1) or 1))
        untung_val = float(r.get('H', hj_val - hb_val) or (hj_val - hb_val))
        margin_val = float(r.get('J', (untung_val / hj_val) if hj_val else 0) or 0)
        tgl_val = parse_date(r.get('B'))
        bayar_val = (r.get('G') or 'CASH').strip()
        prod_val = prod.strip()

        c.execute('''
            INSERT INTO penjualan (tanggal, nama_produk, qty, harga_beli, harga_jual, pembayaran, keuntungan, margin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tgl_val, prod_val, qty_val, hb_val, hj_val, bayar_val, untung_val, margin_val))
        inserted += 1
    except Exception as e:
        print('Skipping row:', r, 'error:', e)

conn.commit()
conn.close()
print(f"Successfully migrated {inserted} rows from Excel to SQLite DB ({DB_PATH})")
