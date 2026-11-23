
import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="your_mysql_username",
        password="your_mysql_password",
        database="hospital_queue"
    )
