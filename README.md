# KB Lockup Bot

Korean IPO lockup schedule tracking system that extracts, analyzes, and alerts on shareholder lockup releases from DART (Data Analysis, Retrieval and Transfer System) filings.

## Features

### Data Extraction
- **DART API Integration** - Automatic prospectus document retrieval
- **Hybrid AI + Rule-based Extraction** - Uses Qwen AI with rule-based fallback for table parsing
- **Korean Document Processing** - Handles Korean date formats, number units (만주, 천주), and ownership percentages

### Market Data Integration
- **Real-time KRX Data** - Current prices and trading volumes via pykrx
- **Exit Analysis** - Estimates days to liquidate positions based on trading volume
- **Value Estimation** - Calculates position values in KRW

### Analysis
- **Blockdeal Opportunities** - Scores and ranks upcoming lockup releases
- **Market Impact Assessment** - Recommendations based on position size vs daily volume
- **D-Day Tracking** - Countdown to lockup release dates

### Interfaces
- **Telegram Bot** - Search, alerts, and notifications
- **Web Dashboard** - Streamlit-based UI for analysis
- **Excel Export** - Export data with xlwings integration

## Installation

```bash
# Clone the repository
git clone https://github.com/SaesolAhn/kb_lockupbot.git
cd kb_lockupbot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .
```

## Configuration

Create a `.env` file in the project root:

```env
# Required
DART_API_KEY=your_dart_api_key

# Optional - for AI extraction
QWEN_API_KEY=your_qwen_api_key

# Optional - for Telegram bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

Get your DART API key from [DART OpenAPI](https://opendart.fss.or.kr/).

## Usage

### Command Line

```bash
# Extract lockup data for a company
python -m kb_lockup extract "삼성전자"

# Search existing data
python -m kb_lockup search "리브스메드"

# Run Telegram bot
python -m kb_lockup bot

# Run web dashboard
python -m kb_lockup web
```

### Python API

```python
import asyncio
from kb_lockup.storage.database import Database
from kb_lockup.analysis.exit_analysis import ExitAnalyzer
from kb_lockup.analysis.market_data import get_market_data_service

async def analyze_company():
    # Get market data
    svc = get_market_data_service()
    info = svc.get_stock_info("005930")  # Samsung
    print(f"Price: {info['current_price']:,} KRW")

    # Search lockup data
    db = Database()
    await db.connect()

    results = await db.search_lockup("삼성전자")
    for r in results:
        print(f"{r.owner}: {r.amount:,}주 ({r.ratio}%)")

    # Exit analysis
    analyzer = ExitAnalyzer(db)
    opportunities = await analyzer.analyze_exit_candidates(days_ahead=30)

    await db.close()

asyncio.run(analyze_company())
```

### Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/search <company>` | Search lockup data by company name |
| `/upcoming [days]` | Show upcoming lockup releases |
| `/remind <company> <days>` | Set reminder for lockup release |
| `/reminders` | List active reminders |
| `/blockdeal [min_ratio]` | Find blockdeal opportunities |
| `/export <company>` | Export data to Excel |
| `/stats` | Show database statistics |

## Project Structure

```
kb_lockup/
├── analysis/          # Exit analysis, blockdeal detection, market data
├── core/              # Models, constants, exceptions
├── dart/              # DART API client, document parser
├── export/            # Excel export, message formatting
├── extraction/        # Table finder, AI/rule extractors, normalizer
├── storage/           # SQLite database, migrations
├── telegram_bot/      # Bot handlers, scheduler
├── web/               # Streamlit dashboard
└── main.py            # CLI entry point
```

## Data Model

### Lockup Entry
- **Owner** - Exact shareholder name (preserved as-is from source)
- **Amount** - Number of shares
- **Ratio** - Ownership percentage
- **Release Date** - Lockup expiration date
- **Period** - Lock period in months
- **Remarks** - Additional notes

### Example Output

```
📋 리브스메드 (491000) - Lockup Schedule

  타임폴리오 소부장 그로쓰 신기술투자조합 제1호
    850,000주 (2.64%) | D-30

  삼성증권주식회사(타임폴리오 The Time-Q 일반사모투자신탁)
    430,000주 (1.34%) | D-30

  김철수(대표이사)
    5,200,000주 (16.17%) | D-180
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=kb_lockup
```

## Dependencies

- **pykrx** - Korean stock market data
- **httpx** - Async HTTP client for DART API
- **aiosqlite** - Async SQLite database
- **beautifulsoup4** - HTML/XML parsing
- **python-telegram-bot** - Telegram bot framework
- **streamlit** - Web dashboard
- **pandas/openpyxl** - Excel export

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests (`pytest tests/ -v`)
5. Submit a pull request
