import sqlite3
import bcrypt


def init_db():
    conn = sqlite3.connect("database.db")
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    cur.execute("""
CREATE TABLE IF NOT EXISTS mcq_answers(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
question_id INTEGER,
selected_option TEXT,
is_correct INTEGER,
FOREIGN KEY(user_id) REFERENCES users(id),
FOREIGN KEY(question_id) REFERENCES mcq_questions(id)
)
""")

    # USERS TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password BLOB NOT NULL,
        role TEXT DEFAULT 'candidate'
    )
    """)

    # INTERVIEWS TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS interviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER,
        score INTEGER,
        feedback TEXT,
        recording TEXT,
        status TEXT DEFAULT 'Pending',
        FOREIGN KEY(candidate_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # CODING PROBLEMS TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS coding_problems(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        difficulty TEXT,
        description TEXT NOT NULL
    )
    """)

    # TEST CASES TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS testcases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        problem_id INTEGER,
        input TEXT,
        output TEXT,
        FOREIGN KEY(problem_id) REFERENCES coding_problems(id) ON DELETE CASCADE
    )
    """)

    # SUBMISSIONS TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        problem_id INTEGER,
        code TEXT,
        result TEXT,
        score INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(problem_id) REFERENCES coding_problems(id)
    )
    """)

    # MCQ QUESTIONS TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mcq_questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_number INTEGER,
        question TEXT NOT NULL,
        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,
        answer TEXT NOT NULL
    )
    """)

    # PROFILES TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS profiles(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone TEXT,
        college TEXT,
        skills TEXT,
        photo TEXT,
        resume TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # CREATE DEFAULT ADMIN
    cur.execute("SELECT id FROM users WHERE email = ?", ("admin@gmail.com",))
    admin = cur.fetchone()

    if admin is None:
        hashed_password = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt())

        cur.execute("""
        INSERT INTO users (name, email, password, role)
        VALUES (?, ?, ?, ?)
        """, ("Admin", "admin@gmail.com", hashed_password, "admin"))

    conn.commit()
    conn.close()