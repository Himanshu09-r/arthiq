# ARTHIQ — voice-first kirana business assistant

ARTHIQ combines a shop dashboard with voice-assisted customer ledger, collections, inventory and daily business reporting. The existing dashboard and its customer, ledger, collections, inbox and insights pages are retained.

## Run locally
Use Python 3.10 or newer. From the project folder:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Edit `.env` and add the API credentials for the speech provider you have access to. Do not commit `.env` or share it in project archives. The example file contains placeholders only. The voice provider cannot be verified until valid credentials and provider access are configured.

Start the app:

```bash
uvicorn app.api.main:app --reload
```

Open `http://127.0.0.1:8000`. The app initializes its database and applies non-destructive migrations on startup. By default it uses `sqlite:///arthiq.db`; set `DATABASE_URL` in `.env` to use a different database.

## Voice assistant

The regular microphone button remains available. For hands-free use, press **Enable Hands-Free** once and grant microphone access. The browser performs voice-activity detection while the page is open and in the foreground. It sends short captured clips to the configured speech service and checks wake phrases such as:

- “Suno ARTHIQ”
- “ARTHIQ SUNO”
- “Hey ARTHIQ”

After the wake phrase, speak the command. Stock receipt commands are read back and require a spoken “yes” before inventory is changed. “No” cancels the pending stock entry. Hands-free pauses when the browser tab is in the background; the manual microphone remains the fallback.

Examples:

- “1 kg rice aaya”
- “10 kilo oil aaya hai”
- “20 packet Maggi aaye hain”
- “Aaj ki summary do”
- “Aaj ka hisaab batao”

## Inventory and CSV import

The stock modal includes a CSV preview and one-time commit flow. Both the bundled catalogue (`data/arthiq_item_price_list.csv`) and the stock-upload template (`/inventory/stock-import-template.csv`) use exactly these six columns, in this order:

```csv
name,unit,price,cost_price,stock_qty,reorder_level
```

`price` is the selling price, `cost_price` is the purchase cost, and `stock_qty` is the quantity being received in a stock import. Incoming quantity is added to existing on-hand stock; a blank or zero quantity makes no stock change. Import previews validate the rows before commit, and a preview token cannot be committed twice. Stock movements are recorded through the purchase/movement engine. Product SKU, category, pack size, supplier hints and aliases are stored separately in `data/arthiq_item_price_list_metadata.json`; they are not extra CSV columns. The bundled product-catalogue seeder (`python import_catalogue.py`) adds product metadata without changing stock; use the stock-import screen to record actual receipts.

## Daily summary

The dashboard summary and voice summary read business data from the database: cash sales, credit sales, money collected, customer outstanding and overdue dues, stock received and stock warnings. Generating a summary is read-only; reminder sending remains a separate, explicit dashboard approval action.

## Languages

The application exposes the supported languages in `/languages`. Legacy `od-IN` shop and customer preferences are migrated to Hindi (`hi-IN`); Odia is not offered as a selectable application language. Other supported languages are retained.

## Tests

```bash
PYTHONPATH=. pytest -q
python -m compileall -q app tests
```

The tests use temporary SQLite databases. Speech-to-text and text-to-speech provider calls require valid configured credentials and are not covered by the offline unit tests.

## Key safeguards

1. Monetary totals, customer balances and stock quantities are calculated by application code and database operations, not by the language model.
2. Voice stock-in requires explicit confirmation before writing.
3. Stock changes are applied through the stock movement engine, avoiding direct-update plus movement double counting.
4. CSV imports preview first, add incoming quantity, and reject a reused commit token.
5. Daily summaries do not send reminders or perform other write actions.
6. Existing dashboard pages and workflows are preserved; the added inventory view is available at `/inventory/page`.
