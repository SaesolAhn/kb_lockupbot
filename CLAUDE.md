# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KB Lockup Bot is a Korean IPO lockup schedule tracking system. This version uses **DART (Data Analysis, Retrieval and Transfer System)** integration to extract lockup data from prospectus filings. It employs a hybrid approach using **Qwen AI** (LLM) and rule-based parsing to extract tables from HWP/HTML documents.

## Commands

```bash
# Install
pip install -e .            # core
pip install -e ".[dev]"     # + pytest, black, ruff

# Extraction (DART + AI)
python -m kb_lockup extract "삼성전자"           # Extract specific company
python -m kb_lockup extract --limit 5           # Extract recent IPOs

# Search
python -m kb_lockup search "리브스메드"

# Run Interfaces
python -m kb_lockup web                         # Streamlit dashboard
python -m kb_lockup bot                         # Telegram bot

# Tests
pytest tests/ -v
pytest tests/ --cov=kb_lockup
pytest tests/ -k "test_name"        # single test

# Linting & formatting
black kb_lockup/ --line-length 100
ruff check kb_lockup/
ruff check --fix kb_lockup/
```

## Architecture

### Data Flow

```
DART API ──→ VartClient ──→ Downloader ──→ Parser (HWP/HTML)
                                                │
                                                ▼
                                    TableFinder & Extractor (AI/Rule)
                                                │
                                                ▼
                                    Normalizer ──→ Storage (SQLite)
                                                │
                                                ▼
                                    Dashboard / Bot / Analysis
```

### Key Modules

- **`dart/`** — DART API integration. `client.py` for API calls, `downloader.py` for docs.
- **`extraction/`** — Core extraction logic:
    - `qwen_extractor.py`: LLM-based table extraction.
    - `rule_extractor.py`: Heuristic table parsing.
    - `table_finder.py`: Locates "protection" or "lockup" tables.
    - `pipeline.py`: Orchestrates the extraction flow.
- **`storage/`** — Async SQLite handling (`database.py`, `models.py`).
- **`analysis/`** — Market data integration (pykrx) and Exit Analysis.
- **`web/`** — Streamlit dashboard.
- **`telegram_bot/`** — Telegram interface.

## Configuration

`.env` file in project root:
```
DART_API_KEY=...           # Required
QWEN_API_KEY=...           # Required for AI extraction
TELEGRAM_BOT_TOKEN=...     # Required for Bot
```

## Code Style

- Python 3.10+, line length 100 (black + ruff)
- ruff rules: E, W, F, I (isort), B (bugbear), C4 (comprehensions); E501 ignored
- pytest with `asyncio_mode = "auto"` — async tests run automatically
- **Note**: This branch relies heavily on `kb_lockup/extraction` module which was removed in later SEIBro versions.
