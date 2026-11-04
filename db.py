import os

import pymysql
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    password = os.getenv("MYSQLPASSWORD") or os.getenv("MYSQL_PASSWORD")

    return pymysql.connect(
        host=os.getenv("MYSQLHOST", "127.0.0.1"),
        port=int(os.getenv("MYSQLPORT", "3306")),
        user=os.getenv("MYSQLUSER", "bincom_user"),
        password=password,
        database=os.getenv("MYSQLDATABASE", "bincom"),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


if __name__ == "__main__":
    connection = get_connection()
    print("Python connected to MySQL successfully.")

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS polling_unit_count FROM polling_unit")
        print("Polling units:", cursor.fetchone()["polling_unit_count"])

    connection.close()