import os

import pymysql
from dotenv import load_dotenv


load_dotenv()


def get_connection():
    return pymysql.connect(
        host="127.0.0.1",
        port=3306,
        user="bincom_user",
        password=os.environ["MYSQL_PASSWORD"],
        database="bincom",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


if __name__ == "__main__":
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM polling_unit"
            )
            result = cursor.fetchone()

            print("Python connected to MySQL successfully.")
            print("Polling units:", result["total"])
    finally:
        connection.close()