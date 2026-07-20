import os
from pathlib import Path
import psycopg

host = "172.18.0.4"
port = 5432
user = "ntc_app"
database = "ntc_rag"

for pw in ["ntc_secure_pass_2024", "ntc_secure_pass_2024\n"]:
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=pw,
            dbname=database,
            connect_timeout=2
        )
        print(f"SUCCESS with password representation: {repr(pw)}")
        conn.close()
        break
    except Exception as e:
        print(f"FAILED with password representation: {repr(pw)}: {e}")
