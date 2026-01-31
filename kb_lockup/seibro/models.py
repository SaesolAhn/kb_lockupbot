from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, BigInteger, Numeric, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class SeibroUnstakingSchedule(Base):
    __tablename__ = 'seibro_unstaking_schedule'

    id = Column(Integer, primary_key=True, autoincrement=True)
    short_code = Column(String, index=True, nullable=False)
    company_name = Column(String, nullable=False)
    stock_type = Column(String)
    issue_type = Column(String)
    market_type = Column(String, index=True)
    deposit_date = Column(Date)
    deposit_shares = Column(BigInteger)
    return_date = Column(Date, index=True)
    return_shares = Column(BigInteger)
    reason = Column(String)
    total_shares = Column(BigInteger, nullable=True)
    
    # Enrichment fields
    stake_portion_pct = Column(Numeric, nullable=True)
    stock_current_price_krw = Column(Numeric, nullable=True)
    current_stake_value_million_krw = Column(Numeric, nullable=True)
    
    # AI Analysis fields
    block_deal_score = Column(Integer, nullable=True)  # 0-100
    block_deal_analysis = Column(String, nullable=True) # Text explanation
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint('short_code', 'return_date', 'deposit_date', 'return_shares', 
                         name='uq_seibro_unstaking_row'),
    )

    def __repr__(self):
        return f"<SeibroUnstakingSchedule(code={self.short_code}, name={self.company_name}, return={self.return_date})>"
