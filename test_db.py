from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("DATABASE URL:", DATABASE_URL)

try:
    engine = create_engine(DATABASE_URL)

    with engine.connect() as connection:
        print("✅ PostgreSQL connected successfully!")

except Exception as e:
    print("❌ Connection failed")
    print(e)