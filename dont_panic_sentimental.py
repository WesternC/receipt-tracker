import psycopg2

# 1. Open the connection
conn = psycopg2.connect(
    dbname="dont-panic",
    user="postgres",
    password="8patH6M2w2nc:DY",
    host="localhost",
    port="5432"
)

# 2. Open a cursor
cur = conn.cursor()

# 3. Execute a test query
cur.execute("SELECT version();")
db_version = cur.fetchone()
print(f"Connected to: {db_version[0]}")

# 4. Close the cursor and connection
cur.close()
conn.close()