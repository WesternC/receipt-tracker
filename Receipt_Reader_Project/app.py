from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
import psycopg
from psycopg import errors
from psycopg.rows import dict_row
import receipt_reader
from receipt_reader import process_receipt_image, VALID_GROCERIES
from werkzeug.utils import secure_filename
import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("user_password")

        try:
            with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, password
                        FROM users
                        WHERE username = %s
                    """, (username,))
                    user_record = cur.fetchone()

        except psycopg.Error as e:
            flash("Login failed, please try again.")
            print(f"Database error: {e}")
            return redirect(url_for('home'))

        if user_record is None or not check_password_hash(user_record[1], password):
            flash("Incorrect username or password")
            return redirect(url_for('home'))

        session["user_id"] = user_record[0]
        session["username"] = username

        print(f"User {username} logged in successfully!")
        return redirect(url_for('welcome'))

    return render_template("index.html")

@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # 1. Validation checks
        if not username or not password:
            flash("All fields are required.")
            return redirect(url_for('register'))

        if len(username) > 24:
            flash("Username must be 24 characters or fewer.")
            return redirect(url_for('register'))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for('register'))

        # 2. Hash password
        hashed_password = generate_password_hash(password)

        # 3. Database insert
        try:
            with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (username, password)
                        VALUES (%s, %s)
                        RETURNING id;
                    """, (username, hashed_password))
                conn.commit()

        except errors.UniqueViolation:
            flash("That username is already taken.")
            return redirect(url_for('register'))

        except psycopg.Error as e:
            flash("Registration failed. Please try again.")
            print(f"Database error: {e}")
            return redirect(url_for('register'))
        
        return redirect(url_for('home'))

    return render_template('register.html')

@app.route('/welcome')
def welcome():
    if "username" not in session:
        return redirect(url_for('home'))
    return render_template('welcome.html')

@app.route('/upload', methods=["GET","POST"])
def upload():
    if "user_id" not in session:
        flash("You must be logged in to upload a receipt.")
        return redirect(url_for('home'))
    if request.method == "POST":
        try:
            image_file = request.files.get("receipt_image")
            if not image_file:
                flash("No file uploaded.")
                return redirect(url_for('welcome'))
            filename = secure_filename(image_file.filename)
            image_file.save(filename)
            process_receipt_image(filename, session["user_id"])
            os.remove(filename)
            flash("Receipt processed successfully!")
        except Exception as e:
            print(f"UPLOAD CRASHED: {str(e)}")
            flash(f"An error occurred while processing the receipt: {str(e)}")
            return redirect(url_for('welcome'))
        return redirect(url_for('welcome'))
    return render_template("upload.html")

@app.route('/history', methods=["GET", "POST"])
def history():
    if "user_id" not in session:
        flash("You must be logged in to view your receipt history.")
        return redirect(url_for('home'))
    try:
        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT receipts.id, merchants.name, receipts.purchase_total, receipts.receipt_date, receipt_items.category, receipt_items.item, receipt_items.price
                    FROM receipts
                    JOIN merchants ON receipts.merchant_id = merchants.id
                    JOIN receipt_items ON receipts.id = receipt_items.receipt_id
                    WHERE receipts.user_id = %s
                    ORDER BY receipts.receipt_date DESC;
                    """, (session["user_id"],))
                table = cur.fetchall()
                receipt_dict = {}
                for row in table:
                    purchases_tuple = row["item"], row["category"], row["price"]
                    if row["id"] not in receipt_dict:
                        receipt_dict[row["id"]] = {"Merchant": row["name"], "Date": row["receipt_date"], "Purchases": [purchases_tuple], "Total": row["purchase_total"]}
                    else:
                        receipt_dict[row["id"]]["Purchases"].append(purchases_tuple)
        return render_template('history.html', receipts_data=receipt_dict)


    except psycopg.Error as e:
        flash("Failed to retrieve receipt history. Please try again.")
        print(f"Database error: {e}")
        return redirect(url_for('welcome'))

@app.route('/dashboard', methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        flash("You must be logged in to view your receipt history.")
        return redirect(url_for('home'))

    if request.method == "POST":
        try:
            time_increment = request.form.get('time_increment', 'month')
            time_filter = request.form.get('by_time')
            item_filter = request.form.get("by_item")
            category_filter = request.form.get("by_category")


        except Exception as e:
            flash(f"An error occurred while processing: {str(e)}")
            return redirect(url_for('welcome'))

        core_query = """
        SELECT SUM(receipt_items.price) AS total_expense, DATE_TRUNC(%s, receipts.receipt_date) AS date_period
        FROM receipts
        JOIN merchants ON receipts.merchant_id = merchants.id
        JOIN receipt_items ON receipts.id = receipt_items.receipt_id
        """
        query_variables = []
        query_variables.append(time_increment)
        core_query += " WHERE receipts.user_id = %s"
        query_variables.append(session["user_id"])
        
        if item_filter:
            core_query += " AND receipt_items.item = %s"
            query_variables.append(item_filter)
        elif category_filter:
            core_query += " AND receipt_items.category = %s"
            query_variables.append(category_filter)
        if time_filter:
            core_query += " AND receipts.receipt_date >= CURRENT_DATE - %s::INTERVAL"
            query_variables.append(time_filter)

        core_query += " GROUP BY date_period ORDER BY date_period"
                
        try:
            with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:
                    cur.execute(core_query, query_variables)
                    raw_table = cur.fetchall()
                    table = []
                    for row in raw_table:
                        total_spent = row[0]
                        raw_date = row[1]
                        if time_increment == 'year':
                            clean_date = raw_date.strftime('%Y')
                        elif time_increment == 'month':
                            clean_date = raw_date.strftime('%B %Y')
                        else:
                            clean_date = raw_date.strftime('%b %d, %Y')
                        table.append((total_spent, clean_date))
            return render_template('dashboard.html', table_data=table, valid_groceries=VALID_GROCERIES)

        except psycopg.Error as e:
            flash("Failed to parse data. Please try again.")
            print(f"Database error: {e}")
            return redirect(url_for('welcome'))

    return render_template('dashboard.html', valid_groceries=VALID_GROCERIES)


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(debug=True)

