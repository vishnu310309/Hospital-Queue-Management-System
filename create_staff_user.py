from db_config import get_db_connection
from werkzeug.security import generate_password_hash
from getpass import getpass

username = input("Enter Doctor Username: ")
password = getpass("Enter Doctor Password: ")
doctor_id = int(input("Enter Doctor ID: "))

password_hash = generate_password_hash(password)

conn = get_db_connection()
cursor = conn.cursor()

try:
    cursor.execute("""
        INSERT INTO staff_users
        (username, password_hash, role, doctor_id)
        VALUES (%s, %s, 'doctor', %s)
    """, (username, password_hash, doctor_id))

    conn.commit()
    print("Doctor account created successfully!")

except Exception as e:
    conn.rollback()
    print("Error:", e)

finally:
    cursor.close()
    conn.close()