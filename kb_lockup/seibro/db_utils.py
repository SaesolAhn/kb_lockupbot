from contextlib import contextmanager
from typing import List, Dict, Any, Generator
from pathlib import Path
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from kb_lockup.config import settings
from kb_lockup.seibro.models import Base, SeibroUnstakingSchedule

logger = logging.getLogger(__name__)

# Ensure absolute path for SQLite
db_path = settings.db_path.absolute()
DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initializes the database tables."""
    Base.metadata.create_all(bind=engine)

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Yields a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def upsert_unstaking_rows(rows: List[Dict[str, Any]]):
    """
    Upserts unstaking schedule rows into the database.
    Updates existing rows based on the unique constraint (short_code, return_date, deposit_date, return_shares).
    """
    if not rows:
        return

    # Ensure tables exist
    init_db()

    session = SessionLocal()
    try:
        for row in rows:
            # Prepare data
            # Filter keys that match the model
            stmt = sqlite_insert(SeibroUnstakingSchedule).values(row)
            
            # Define conflict update columns
            # We want to refresh everything except the key columns and created_at
            # Keys: short_code, return_date, deposit_date, return_shares
            
            update_dict = {
                "company_name": stmt.excluded.company_name,
                "stock_type": stmt.excluded.stock_type,
                "issue_type": stmt.excluded.issue_type,
                "market_type": stmt.excluded.market_type,
                "deposit_shares": stmt.excluded.deposit_shares,
                "reason": stmt.excluded.reason,
                "total_shares": stmt.excluded.total_shares,
                "stake_portion_pct": stmt.excluded.stake_portion_pct,
                "stock_current_price_krw": stmt.excluded.stock_current_price_krw,
                "current_stake_value_million_krw": stmt.excluded.current_stake_value_million_krw,
                "updated_at": datetime.now()
            }
            
            # Execute upsert
            do_update_stmt = stmt.on_conflict_do_update(
                index_elements=['short_code', 'return_date', 'deposit_date', 'return_shares'],
                set_=update_dict
            )
            
            session.execute(do_update_stmt)
            
        session.commit()
        logger.info(f"Upserted {len(rows)} rows into seibro_unstaking_schedule.")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error upserting rows: {e}")
        raise
    finally:
        session.close()

from datetime import datetime
