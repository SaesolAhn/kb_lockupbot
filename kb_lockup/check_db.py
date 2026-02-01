
import asyncio
from kb_lockup.storage.database import Database
from pathlib import Path

async def main():
    db_path = Path("data/kb_lockup.db")

    with open("db_status.txt", "w") as f:
        f.write(f"Checking DB at: {db_path.absolute()}\n")
        if not db_path.exists():
            f.write("DB file does not exist!\n")
            return

        async with Database(db_path) as db:
            stats = await db.get_stats()
            f.write(f"DB Stats: {stats}\n")
            
            companies = await db.get_companies_list()
            f.write(f"Companies: {companies}\n")
            
            rows = await db.conn.execute("SELECT company_name, COUNT(*) as count FROM lockup_data GROUP BY company_name")
            counts = await rows.fetchall()
            for c in counts:
                f.write(f"{c['company_name']}: {c['count']} entries\n")

if __name__ == "__main__":
    asyncio.run(main())
