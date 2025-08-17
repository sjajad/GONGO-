# app.py
import os, sqlite3, hashlib, datetime
from flask import Flask, render_template, request, redirect, url_for, session, g, flash, jsonify

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "data", "eduprep.db")
os.makedirs(os.path.join(APP_DIR, "data"), exist_ok=True)

app = Flask(__name__)
app.secret_key = "change_this_secret_to_a_random_string"

# ---------- DB helpers ----------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    get_db().commit()
    return (rv[0] if rv else None) if one else rv

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ---------- init db ----------
def init_db():
    db = get_db()
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        grade TEXT,
        term TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subject_id INTEGER,
        created_at TEXT,
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    );
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER,
        question TEXT,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        correct TEXT,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
    );
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        quiz_id INTEGER,
        student_name TEXT,
        score INTEGER,
        total INTEGER,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
    );
    """
    db.executescript(schema)
    db.commit()

# ---------- utils ----------
def hashpw(p):
    return hashlib.sha256(p.encode()).hexdigest()

def current_time():
    return datetime.datetime.utcnow().isoformat()

# ---------- routes ----------
@app.route("/")
def index():
    quizzes = query_db("""
        SELECT q.*, s.name AS subject_name, s.grade, s.term
        FROM quizzes q
        LEFT JOIN subjects s ON q.subject_id = s.id
        ORDER BY q.id DESC
    """)
    return render_template("index.html", quizzes=quizzes, user=session.get("user"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if not username or not password:
            flash("املأ الحقول.")
            return redirect(url_for("register"))
        try:
            query_db("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                     (username, hashpw(password), current_time()))
            flash("تم إنشاء الحساب. سجل الدخول الآن.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("اسم المستخدم موجود مسبقاً.")
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        if user and user["password"] == hashpw(password):
            session["user"] = {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}
            flash("مرحباً، تم تسجيل الدخول.")
            return redirect(url_for("dashboard"))
        flash("بيانات غير صحيحة.")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("تم تسجيل الخروج.")
    return redirect(url_for("index"))

@app.route("/dashboard")
def dashboard():
    if not session.get("user"):
        return redirect(url_for("login"))
    quizzes = query_db("""
        SELECT q.*, s.name AS subject_name, s.grade, s.term
        FROM quizzes q
        LEFT JOIN subjects s ON q.subject_id = s.id
        ORDER BY q.id DESC
    """)
    attempts = query_db("""
        SELECT a.*, q.title 
        FROM attempts a 
        LEFT JOIN quizzes q ON a.quiz_id=q.id 
        WHERE user_id=? 
        ORDER BY a.id DESC
    """, (session["user"]["id"],))
    return render_template("dashboard.html", quizzes=quizzes, attempts=attempts, user=session.get("user"))

@app.route("/quiz/<int:quiz_id>", methods=["GET","POST"])
def take_quiz(quiz_id):
    quiz = query_db("SELECT * FROM quizzes WHERE id=?", (quiz_id,), one=True)
    if not quiz:
        return "Quiz not found", 404

    questions = query_db("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    if request.method == "POST":
        if not session.get("user"):
            return redirect(url_for("login"))
        student_name = request.form.get("student_name", "").strip()
        if not student_name:
            flash("يرجى إدخال اسم الطالب.")
            return redirect(url_for("take_quiz", quiz_id=quiz_id))

        # تحقق من محاولة سابقة
        existing_attempt = query_db("SELECT * FROM attempts WHERE user_id=? AND quiz_id=?", 
                                    (session["user"]["id"], quiz_id), one=True)
        if existing_attempt:
            flash("لقد أجبت هذا الاختبار مسبقاً.")
            return redirect(url_for("dashboard"))

        score = 0
        total = len(questions)
        for q in questions:
            qid = str(q["id"])
            user_ans = request.form.get("q_" + qid, "").upper()
            if user_ans == q["correct"].upper():
                score += 1

        query_db("INSERT INTO attempts (user_id, quiz_id, student_name, score, total, created_at) VALUES (?,?,?,?,?,?)",
                 (session["user"]["id"], quiz_id, student_name, score, total, current_time()))
        flash(f"انتهى الاختبار: النتيجة {score}/{total}")
        return redirect(url_for("dashboard"))

    return render_template("take_quiz.html", quiz=quiz, questions=questions, user=session.get("user"))

# ---------- Admin ----------
@app.route("/admin", methods=["GET","POST"])
def admin():
    if not session.get("user") or not session["user"].get("is_admin"):
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_subject":
            name = request.form["name"].strip()
            grade = request.form["grade"].strip()
            term = request.form["term"].strip()
            if name:
                query_db("INSERT INTO subjects (name, grade, term, created_at) VALUES (?,?,?,?)",
                         (name, grade, term, current_time()))
                flash("تم إضافة المادة.")
        elif action == "create_quiz":
            title = request.form["title"].strip()
            subject_id = int(request.form["subject_id"])
            if title:
                query_db("INSERT INTO quizzes (title, subject_id, created_at) VALUES (?,?,?)",
                         (title, subject_id, current_time()))
                flash("تم إنشاء الاختبار.")
        elif action == "add_question":
            quiz_id = int(request.form["quiz_id"])
            q = request.form["question"].strip()
            a = request.form["a"].strip()
            b = request.form["b"].strip()
            c = request.form["c"].strip()
            d = request.form["d"].strip()
            correct = request.form["correct"].upper().strip()
            if q and correct in ["A","B","C","D"]:
                query_db("INSERT INTO questions (quiz_id, question, option_a, option_b, option_c, option_d, correct) VALUES (?,?,?,?,?,?,?)",
                         (quiz_id, q, a, b, c, d, correct))
                flash("تم إضافة السؤال.")
        elif action == "delete_question":
            qid = int(request.form["question_id"])
            query_db("DELETE FROM questions WHERE id=?", (qid,))
            flash("تم حذف السؤال نهائيًا.")
        return redirect(url_for("admin"))

    subjects = query_db("SELECT * FROM subjects ORDER BY id DESC")
    quizzes = query_db("SELECT q.*, s.name AS subject_name, s.grade, s.term FROM quizzes q LEFT JOIN subjects s ON q.subject_id=s.id ORDER BY q.id DESC")
    questions = query_db("SELECT * FROM questions ORDER BY id DESC")
    return render_template("admin.html", subjects=subjects, quizzes=quizzes, questions=questions, user=session.get("user"))

# ---------- API ----------
@app.route("/api/quizzes")
def api_quizzes():
    quizzes = query_db("SELECT id, title FROM quizzes ORDER BY id DESC")
    return jsonify([dict(x) for x in quizzes])

# ---------- Create default admin ----------
def ensure_admin():
    admin = query_db("SELECT * FROM users WHERE username=?", ("admin",), one=True)
    if not admin:
        query_db("INSERT INTO users (username, password, is_admin, created_at) VALUES (?,?,?,?)",
                 ("admin", hashpw("admin1234"), 1, current_time()))
        print("created default admin (admin/admin1234)")

# ---------- run ----------
if __name__ == "__main__":
    with app.app_context():
        init_db()
        ensure_admin()
    app.run(host="0.0.0.0", port=5000, debug=True)