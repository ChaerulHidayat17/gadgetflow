# 📱 GadgetFlow — Smartphone Inventory, Sales & Telegram Operations Platform

> **High-throughput smartphone reseller inventory management, daily transaction bookkeeping, and interactive Telegram bot automation.**  
> Built by **Chaerul Hidayat** ([@ChaerulHidayat17](https://github.com/ChaerulHidayat17)) for business operations and retail workflow automation.

---

## 🎯 Overview

GadgetFlow powers operations for high-velocity electronics and smartphone reselling (tracking 150+ hardware units and over Rp 1.3B in inventory turnover). It streamlines daily sales logging, stock status, profit margins, and inventory tracking through a unified web dashboard and an interactive Telegram bot.

---

## 🚀 Key Features

* **🤖 Interactive Telegram Bot Operations**:
  * Record sales on-the-fly directly from smartphone chat.
  * Instant stock availability search across popular series (iPhone, POCO, Samsung, Infinix, etc.).
  * Daily profit, capital rotation, and revenue calculation commands.
* **📊 Web Dashboard & Bookkeeping**:
  * Real-time stock overview, margin calculations, and inventory lifecycle states.
  * Fast search and filter by brand, model, storage tier, and status.
* **💾 Resilient Embedded Architecture**:
  * SQLite relational database backend with transactional integrity.
  * Easy Excel/CSV migration tools.

---

## 🛠️ Tech Stack

* **Backend**: Python 3.14 + FastAPI + Uvicorn
* **Bot Engine**: `python-telegram-bot` / `httpx` async event loop
* **Database**: SQLite with indexed relational tables
* **Frontend**: HTML5, Tailwind CSS, Jinja2 Templates

---

## 🏃 Local Setup

```bash
# Clone repository
git clone https://github.com/ChaerulHidayat17/gadgetflow.git
cd gadgetflow

# Create virtual environment & install requirements
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure bot token
cp .env.example .env
# Set your TELEGRAM_BOT_TOKEN in .env or .bot_token

# Run web dashboard
uvicorn app:app --host 0.0.0.0 --port 8080

# Run Telegram bot
python3 bot.py
```
