import psycopg2
from .config import DATABASE_URL

class Db_pg:

    def connect_db():
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        return cur,conn

    def disconnect_db(cur, conn):
        cur.close()
        conn.close()
        