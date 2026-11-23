from flask import Flask, render_template, request, redirect, session
from db_config import get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "hospital_secret_key"


# Login page
@app.route('/')
def home():
    return render_template('login.html')


# Patient registration
@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        name = request.form['patient_name']
        age = request.form['age']
        gender = request.form['gender']  
        phone = request.form['phone']
        username = request.form['username']
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            query = """
            INSERT INTO patients
            (patient_name, age, gender, phone, username, password_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
            """

            cursor.execute(query, (
                name, age, gender, phone,
                username, hashed_password
            ))

            conn.commit()

            return redirect('/')

        except Exception as e:
            conn.rollback()
            return "Registration Error: " + str(e)

        finally:
            cursor.close()
            conn.close()

    return render_template('register.html')



@app.route('/login', methods=['POST'])
def login():

    username = request.form['username']
    password = request.form['password']
    role = request.form.get('role')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if role == 'patient':

            cursor.execute(
                "SELECT * FROM patients WHERE username = %s",
                (username,)
            )

            patient = cursor.fetchone()

            if patient and check_password_hash(
                patient['password_hash'], password
            ):
                session.clear()
                session['patient_id'] = patient['patient_id']
                session['patient_name'] = patient['patient_name']
                session['role'] = 'patient'

                return redirect('/dashboard')

        elif role in ['doctor', 'admin']:

            cursor.execute("""
                SELECT * FROM staff_users
                WHERE username = %s AND role = %s
            """, (username, role))

            staff = cursor.fetchone()

            if staff and check_password_hash(
                staff['password_hash'], password
            ):
                session.clear()
                session['staff_id'] = staff['user_id']
                session['role'] = role

                if role == 'admin':
                    return redirect('/admin-panel')

                return redirect('/doctor-panel')

        return "Invalid Username, Password or Role"

    finally:
        cursor.close()
        conn.close()



# Dashboard
@app.route('/dashboard')
def dashboard():

    if 'patient_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return render_template(
        'dashboard.html',
        patient_name=session['patient_name'],
        total_patients=total_patients
    )
# Doctor List
@app.route('/doctors')
def doctors():

    if 'patient_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM doctors")
    doctor_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'doctors.html',
        doctors=doctor_list
    )


# Logout
@app.route('/logout')
def logout():

    session.clear()
    return redirect('/')
# Symptom Selection
@app.route('/symptoms', methods=['GET', 'POST'])
def symptoms():

    if 'patient_id' not in session:
        return redirect('/')

    if request.method == 'POST':

        problem = request.form['problem']

        doctor_mapping = {
            'Fever': 'General Physician',
            'Headache': 'General Physician',
            'Heart Problem': 'Cardiologist',
            'Eye Problem': 'Ophthalmologist',
            'Skin Problem': 'Dermatologist',
            'Tooth Pain': 'Dentist',
            'Bone Pain': 'Orthopedist'
        }

        specialization = doctor_mapping[problem]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM doctors WHERE specialization = %s AND availability = 'Available'",
            (specialization,)
        )

        doctor_list = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            'recommendations.html',
            doctors=doctor_list,
            problem=problem
        )

    return render_template('symptoms.html')
# Generate Patient Token
@app.route('/book-token', methods=['POST'])
def book_token():

    if 'patient_id' not in session:
        return redirect('/')

    doctor_id = request.form['doctor_id']
    patient_id = session['patient_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Generate next token number for today's queue
        cursor.execute("""
            SELECT COALESCE(MAX(token_number), 0) + 1 AS next_token
            FROM tokens
            WHERE doctor_id = %s
            AND DATE(booking_time) = CURDATE()
        """, (doctor_id,))

        token_number = cursor.fetchone()['next_token']

        # Save token
        cursor.execute("""
            INSERT INTO tokens
            (patient_id, doctor_id, token_number,
             token_status, booking_time)
            VALUES (%s, %s, %s, 'Waiting', NOW())
        """, (patient_id, doctor_id, token_number))

        conn.commit()

        # Count patients waiting before this patient
        cursor.execute("""
            SELECT COUNT(*) AS waiting
            FROM tokens
            WHERE doctor_id = %s
            AND DATE(booking_time) = CURDATE()
            AND token_number < %s
            AND token_status IN ('Waiting', 'Consulting')
        """, (doctor_id, token_number))

        waiting = cursor.fetchone()['waiting']

        # Get doctor details
        cursor.execute(
            "SELECT doctor_name FROM doctors WHERE doctor_id = %s",
            (doctor_id,)
        )

        doctor = cursor.fetchone()

        return render_template(
            'token.html',
            token_number=token_number,
            doctor=doctor['doctor_name'],
            waiting=waiting,
            waiting_time=waiting * 10
        )

    except Exception as e:
        conn.rollback()
        return "Token Error: " + str(e)

    finally:
        cursor.close()
        conn.close()
        # Live Queue Tracking

# Live Queue Tracking
@app.route('/my-queue')
def my_queue():

    if 'patient_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT t.*, d.doctor_name
            FROM tokens t
            JOIN doctors d
            ON t.doctor_id = d.doctor_id
            WHERE t.patient_id = %s
            ORDER BY t.token_id DESC
        """, (session['patient_id'],))

        tokens = cursor.fetchall()

        if not tokens:
            return "You have not booked any token yet."

        for token in tokens:

            cursor.execute("""
                SELECT COUNT(*) AS waiting
                FROM tokens
                WHERE doctor_id = %s
                AND DATE(booking_time) = DATE(%s)
                AND token_number < %s
                AND token_status IN ('Waiting', 'Consulting')
            """, (
                token['doctor_id'],
                token['booking_time'],
                token['token_number']
            ))

            waiting = cursor.fetchone()['waiting']

            token['waiting'] = waiting
            token['waiting_time'] = waiting * 10

        return render_template(
            'queue.html',
            tokens=tokens
        )

    finally:
        cursor.close()
        conn.close()

        # Doctor Panel
@app.route('/doctor-panel')
def doctor_panel():

    if session.get('role') != 'doctor':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                t.token_id,
                t.token_number,
                t.token_status,
                p.patient_name
            FROM tokens t
            JOIN patients p
            ON t.patient_id = p.patient_id
            WHERE DATE(t.booking_time) = CURDATE()
            AND t.doctor_id = (
                SELECT doctor_id
                FROM staff_users
                WHERE user_id = %s
            )
            ORDER BY t.token_number ASC
        """, (session['staff_id'],))

        patients = cursor.fetchall()

        return render_template(
            'doctor_panel.html',
            patients=patients
        )

    finally:
        cursor.close()
        conn.close()
        # Update Token Status
@app.route('/update-token/<int:token_id>', methods=['POST'])
def update_token(token_id):

    if session.get('role') != 'doctor':
        return redirect('/')

    status = request.form['status']

    if status not in ['Consulting', 'Completed']:
        return "Invalid Status"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE tokens
            SET token_status = %s
            WHERE token_id = %s
            AND doctor_id = (
                SELECT doctor_id
                FROM staff_users
                WHERE user_id = %s
            )
        """, (status, token_id, session['staff_id']))

        conn.commit()
        return redirect('/doctor-panel')

    finally:
        cursor.close()
        conn.close()
        # Add New Doctor
@app.route('/add-doctor', methods=['POST'])
def add_doctor():
    if session.get('role') != 'admin':
        return redirect('/')

    name = request.form['doctor_name']
    specialization = request.form['specialization']
    phone = request.form['phone']
    availability = request.form['availability']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO doctors
            (doctor_name, specialization, phone, availability)
            VALUES (%s, %s, %s, %s)
        """, (name, specialization, phone, availability))

        conn.commit()

        return redirect('/admin-doctors')

    finally:
        cursor.close()
        conn.close()
        # Manage Doctors
@app.route('/admin-doctors')
def admin_doctors():

    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM doctors")
        doctors = cursor.fetchall()

        return render_template(
            'manage_doctors.html',
            doctors=doctors
        )

    finally:
        cursor.close()
        conn.close()
        # Delete Doctor
@app.route('/delete-doctor/<int:doctor_id>', methods=['POST'])
def delete_doctor(doctor_id):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "DELETE FROM doctors WHERE doctor_id = %s",
            (doctor_id,)
        )

        conn.commit()

        return redirect('/admin-doctors')

    except Exception as e:
        conn.rollback()
        return "Cannot delete doctor: " + str(e)

    finally:
        cursor.close()
        conn.close()
        # Edit Doctor
@app.route('/edit-doctor/<int:doctor_id>')
def edit_doctor(doctor_id):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT * FROM doctors WHERE doctor_id = %s",
            (doctor_id,)
        )

        doctor = cursor.fetchone()

        if doctor is None:
            return "Doctor not found"

        return render_template(
            'edit_doctor.html',
            doctor=doctor
        )

    finally:
        cursor.close()
        conn.close()
        # Update Doctor
@app.route('/update-doctor/<int:doctor_id>', methods=['POST'])
def update_doctor(doctor_id):
    if session.get('role') != 'admin':
        return redirect('/')

    name = request.form['doctor_name']
    specialization = request.form['specialization']
    phone = request.form['phone']
    availability = request.form['availability']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE doctors
            SET doctor_name = %s,
                specialization = %s,
                phone = %s,
                availability = %s
            WHERE doctor_id = %s
        """, (name, specialization, phone, availability, doctor_id))

        conn.commit()

        return redirect('/admin-doctors')

    finally:
        cursor.close()
        conn.close()
        # Manage Patients
@app.route('/admin-patients')
def admin_patients():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT patient_id, patient_name, age, gender, phone
            FROM patients
            ORDER BY patient_id DESC
        """)

        patients = cursor.fetchall()

        return render_template(
            'manage_patients.html',
            patients=patients
        )

    finally:
        cursor.close()
        conn.close()
        # Manage Appointments
@app.route('/admin-appointments')
def admin_appointments():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                a.appointment_id,
                p.patient_name,
                d.doctor_name,
                a.appointment_date,
                a.appointment_time,
                a.appointment_status
            FROM appointments a
            JOIN patients p
                ON a.patient_id = p.patient_id
            JOIN doctors d
                ON a.doctor_id = d.doctor_id
            ORDER BY a.appointment_date DESC
        """)

        appointments = cursor.fetchall()

        return render_template(
            'manage_appointments.html',
            appointments=appointments
        )

    finally:
        cursor.close()
        conn.close()
        # Open Appointment Booking Page
@app.route('/appointment-booking')
def appointment_booking():

    if 'patient_id' not in session:
        return redirect('/')

    from datetime import date

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT * FROM doctors
            WHERE availability = 'Available'
        """)

        doctors = cursor.fetchall()

        return render_template(
            'book_appointment.html',
            doctors=doctors,
            today=date.today().isoformat()
        )

    finally:
        cursor.close()
        conn.close()
        # Save Appointment
@app.route('/book-appointment', methods=['POST'])
def book_appointment():

    if 'patient_id' not in session:
        return redirect('/')

    doctor_id = request.form['doctor_id']
    appointment_date = request.form['appointment_date']
    appointment_time = request.form['appointment_time']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO appointments
            (patient_id, doctor_id, appointment_date,
             appointment_time, appointment_status)
            VALUES (%s, %s, %s, %s, 'Booked')
        """, (
            session['patient_id'],
            doctor_id,
            appointment_date,
            appointment_time
        ))

        conn.commit()

        return """
        <h1>Appointment Booked Successfully!</h1>
        <a href="/dashboard">Back to Dashboard</a>
        """

    except Exception as e:
        conn.rollback()
        return "Appointment Error: " + str(e)

    finally:
        cursor.close()
        conn.close()
@app.route('/cancel-appointment/<int:appointment_id>', methods=['POST'])
def cancel_appointment(appointment_id):
    if session.get('role') != 'admin':
        return redirect('/')
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE appointments
            SET appointment_status = 'Cancelled'
            WHERE appointment_id = %s
        """, (appointment_id,))

        conn.commit()

        return redirect('/admin-appointments')

    finally:
        cursor.close()
        conn.close()
@app.route('/update-appointment/<int:appointment_id>', methods=['POST'])
def update_appointment(appointment_id):
    if session.get('role') != 'admin':
        return redirect('/')

    status = request.form.get('status')

    if status not in ['Confirmed', 'Completed']:
        return "Invalid appointment status"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE appointments
            SET appointment_status = %s
            WHERE appointment_id = %s
        """, (status, appointment_id))

        conn.commit()

        return redirect('/admin-appointments')

    finally:
        cursor.close()
        conn.close()
@app.route('/admin-queue')
def admin_queue():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT t.token_id,
                   t.token_number,
                   t.token_status,
                   p.patient_name,
                   d.doctor_name,
                   t.booking_time
            FROM tokens t
            JOIN patients p ON t.patient_id = p.patient_id
            JOIN doctors d ON t.doctor_id = d.doctor_id
            ORDER BY t.booking_time DESC
        """)

        tokens = cursor.fetchall()

        return render_template(
            'admin_queue.html',
            tokens=tokens
        )

    finally:
        cursor.close()
        conn.close()
@app.route('/my-appointments')
def my_appointments():

    if 'patient_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT a.appointment_id,
                   d.doctor_name,
                   a.appointment_date,
                   a.appointment_time,
                   a.appointment_status
            FROM appointments a
            JOIN doctors d ON a.doctor_id = d.doctor_id
            WHERE a.patient_id = %s
            ORDER BY a.appointment_date DESC
        """, (session['patient_id'],))

        appointments = cursor.fetchall()

        return render_template(
            'patient_appointments.html',
            appointments=appointments
        )

    finally:
        cursor.close()
        conn.close()
@app.route('/patient-cancel-appointment/<int:appointment_id>', methods=['POST'])
def patient_cancel_appointment(appointment_id):

    if 'patient_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE appointments
            SET appointment_status = 'Cancelled'
            WHERE appointment_id = %s
            AND patient_id = %s
            AND appointment_status IN ('Booked', 'Confirmed')
        """, (appointment_id, session['patient_id']))

        conn.commit()

        return redirect('/my-appointments?cancelled=1')

    finally:
        cursor.close()
        conn.close()
@app.route('/reschedule-appointment/<int:appointment_id>')
def reschedule_appointment(appointment_id):

    if 'patient_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM appointments
        WHERE appointment_id = %s
        AND patient_id = %s
    """, (appointment_id, session['patient_id']))

    appointment = cursor.fetchone()

    cursor.close()
    conn.close()

    if not appointment or appointment['appointment_status'] not in ['Booked', 'Confirmed']:
        return redirect('/my-appointments')

    return render_template('reschedule_appointment.html', appointment=appointment)
@app.route('/update-rescheduled-appointment/<int:appointment_id>', methods=['POST'])
def update_rescheduled_appointment(appointment_id):

    if 'patient_id' not in session:
        return redirect('/')

    new_date = request.form['appointment_date']
    new_time = request.form['appointment_time']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE appointments
        SET appointment_date = %s,
            appointment_time = %s
        WHERE appointment_id = %s
        AND patient_id = %s
        AND appointment_status IN ('Booked', 'Confirmed')
    """, (new_date, new_time, appointment_id, session['patient_id']))

    conn.commit()

    cursor.close()
    conn.close()

    return redirect('/my-appointments?rescheduled=1')
# Admin Panel
@app.route('/admin-panel')
def admin_panel():

    if session.get('role') != 'admin':
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM patients")
        total_patients = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM doctors")
        total_doctors = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM tokens")
        total_tokens = cursor.fetchone()[0]

        return render_template(
            'admin_panel.html',
            total_patients=total_patients,
            total_doctors=total_doctors,
            total_tokens=total_tokens
        )

    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    app.run(debug=True)