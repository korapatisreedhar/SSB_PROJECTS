from flask import Flask, request, jsonify, render_template, redirect, session
from flask_jwt_extended import JWTManager
from auth import register_user, login_user
from database import init_db
import sqlite3
import random
import subprocess
import tempfile
import sys

app = Flask(__name__)

app.config["JWT_SECRET_KEY"] = "supersecretkey"
app.secret_key = "secretkey"   # needed for session
jwt = JWTManager(app)

init_db()


@app.route("/")
def home():
    return render_template("login.html")


@app.route("/register_page")
def register_page():
    return render_template("register.html")


@app.route("/register", methods=["POST"])
def register():
    data = request.json
    return register_user(data)

@app.route("/login", methods=["POST"])
def login():

    data = request.json
    email = data.get("email")

    # check credentials using your auth function
    response = login_user(data)

    # if login successful
    if response.status_code == 200:

        conn = sqlite3.connect("database.db")
        cur = conn.cursor()

        cur.execute(
            "SELECT id, role, domain FROM users WHERE email=?",
            (email,)
        )

        user = cur.fetchone()
        conn.close()

        if user is None:
            return jsonify({"error": "User not found"}), 404

        # clear old session
        session.clear()

        session["user_id"] = user[0]
        session["email"] = email
        session["role"] = user[1]
        session["domain"] = user[2] if user[2] else ""

    return response
# DASHBOARD PAGE
@app.route("/dashboard")
def dashboard():

    if "email" not in session:
        return redirect("/")

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT name FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    conn.close()

    name = user[0] if user else "Candidate"

    return render_template("dashboard.html", name=name)
@app.route("/start_coding_test")
def start_coding_test():

    # ✅ login check
    if "email" not in session:
        return redirect("/")

    # 🔥 IMPORTANT: prevent skipping MCQ
    if "mcq_score" not in session:
        return redirect("/mcq_test")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM coding_problems")
    problems = cur.fetchall()

    conn.close()

    if len(problems) < 2:
        return "Not enough coding questions added by admin."

    selected = random.sample(problems, 2)

    # ✅ store selected questions
    session["coding_questions"] = [p[0] for p in selected]

    # ✅ track progress
    session["current_index"] = 0
    session["total_questions"] = len(selected)

    # ✅ open first question
    return redirect(f"/coding_editor/{session['coding_questions'][0]}")


# interview
@app.route("/coding_editor")
@app.route("/coding_editor/<int:problem_id>")
def coding_editor(problem_id=None):

    # ✅ GET QUESTIONS FROM SESSION
    questions = session.get("coding_questions")

    if not questions:
        return redirect("/dashboard")

    index = session.get("current_index", 0)

    # ✅ if no problem_id → load from session using index
    if problem_id is None:
        problem_id = questions[index]

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT title, difficulty, description
        FROM coding_problems
        WHERE id=?
    """, (problem_id,))

    row = cur.fetchone()
    conn.close()

    # ✅ SAFETY CHECK
    if not row:
        return "Problem not found"

    problem = {
        "title": row[0],
        "difficulty": row[1],
        "description": row[2]
    }

    return render_template(
        "coding_editor.html",
        problem=problem,
        problem_id=problem_id,
        current_index=index,
        total_questions=session.get("total_questions", 2)
    )

@app.route("/next_question")
def next_question():

    questions = session.get("coding_questions")
    index = session.get("current_index", 0)

    if not questions:
        return redirect("/dashboard")

    index += 1
    session["current_index"] = index

    # if still questions left
    if index < len(questions):
        return redirect(f"/coding_editor/{questions[index]}")
    else:
        return redirect("/final_submit")
# final sudmit 
@app.route("/final_submit")
def final_submit():

    # clear session test data
    session.pop("coding_questions", None)
    session.pop("current_index", None)
    session.pop("total_questions", None)

    return redirect("/performance")




@app.route("/video_interview")
def video_interview():
    return render_template("video_interview.html")
@app.route("/performance")
def performance():

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # get user id
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        return "User not found"

    user_id = user[0]

    # ================= CODING SCORE =================
    cur.execute("SELECT score FROM coding_results WHERE user_id=?", (user_id,))
    coding_scores = cur.fetchall()

    total_questions = 2   # ✅ fixed number of coding questions

    if coding_scores:
        total_score = sum([s[0] for s in coding_scores])
        coding_score = total_score / total_questions
    else:
        coding_score = 0

    # ================= MCQ SCORE =================
    cur.execute("SELECT score FROM mcq_results WHERE user_id=?", (user_id,))
    mcq = cur.fetchone()

    mcq_score = mcq[0] if mcq else 0

    # ✅ get total MCQs dynamically
    domain = session.get("domain")

    cur.execute("SELECT COUNT(*) FROM mcq_questions WHERE domain=?", (domain,))
    total_mcq = cur.fetchone()[0]

    mcq_percentage = (mcq_score / total_mcq) * 100 if total_mcq else 0

    # ================= FINAL WEIGHTAGE =================
    overall = int((mcq_percentage * 0.6) + (coding_score * 0.4))

    conn.close()

    return render_template(
        "performance.html",
        coding_score=int(coding_score),
        mcq_score=int(mcq_percentage),
        overall=overall
    )
# ===============================
# ADMIN PANEL ROUTES
# ===============================

@app.route("/admin_dashboard")
def admin_dashboard():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users WHERE role='candidate'")
    total_candidates = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM submissions")
    coding_tests = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM interviews")
    ai_interviews = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM interviews WHERE status='Selected'")
    selected_candidates = cur.fetchone()[0]

    cur.execute("""
SELECT 
    users.name,
    users.email,
    COALESCE(submissions.score,0),
    COALESCE(interviews.score,0),
    COALESCE(interviews.status,'Pending'),
    users.id
FROM users
LEFT JOIN submissions 
ON users.id=submissions.user_id
LEFT JOIN interviews 
ON users.id=interviews.candidate_id
WHERE users.role='candidate'
GROUP BY users.id
ORDER BY users.id DESC LIMIT 5
""")

    candidates = cur.fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_candidates=total_candidates,
        coding_tests=coding_tests,
        ai_interviews=ai_interviews,
        selected_candidates=selected_candidates,
        candidates=candidates
    )


# finally result
@app.route("/final_results")
def final_results():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT users.name,
           users.email,
           COALESCE(submissions.score,0),
           COALESCE(interviews.score,0),
           COALESCE(interviews.status,'Pending')
    FROM users
    LEFT JOIN submissions ON users.id = submissions.user_id
    LEFT JOIN interviews ON users.id = interviews.candidate_id
    WHERE users.role='candidate'
    """)

    results = cur.fetchall()

    conn.close()

    return render_template("final_results.html", results=results)


# View Candidates

@app.route("/admin_candidates")
def admin_candidates():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # SHOW ALL USERS (admin + candidate)
    cur.execute("SELECT id,name,email,role,domain FROM users")

    candidates = cur.fetchall()

    conn.close()

    return render_template("admin_candidates.html", candidates=candidates)

# Delete User
@app.route("/delete_user/<int:user_id>")
def delete_user(user_id):

    if "email" not in session:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=?", (user_id,))

    conn.commit()
    conn.close()

    return redirect("/admin_candidates")


# Coding Judge Admin Page
@app.route("/admin_coding_judge")
def admin_coding_judge():
    return render_template("admin_coding_judge.html")
import bcrypt
@app.route("/add_candidate", methods=["POST"])
def add_candidate():

    data = request.json

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role")
    domain = data.get("domain")

    import bcrypt
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode('utf-8')

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    try:
        cur.execute("""
        INSERT INTO users(name,email,password,role,domain)
        VALUES(?,?,?,?,?)
        """,(name,email,hashed,role,domain))

        conn.commit()

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)})   # 🔥 IMPORTANT

    conn.close()

    return jsonify({"message":"Candidate created successfully"})

# Delete Problem
@app.route("/delete_problem/<int:problem_id>")
def delete_problem(problem_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("DELETE FROM coding_problems WHERE id=?", (problem_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Problem deleted"})


# Admin AI Interviews Page
@app.route("/admin_ai_interviews")
def admin_ai_interviews():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT users.name, users.email, interviews.score, interviews.feedback, interviews.recording
    FROM interviews
    JOIN users ON interviews.candidate_id = users.id
    """)

    interviews = cur.fetchall()

    conn.close()

    return render_template("admin_ai_interviews.html", interviews=interviews)


# Admin Results Page
@app.route("/admin_results")
def admin_results():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT users.id,
           users.name,
           users.email,
           COALESCE(submissions.score,0),
           COALESCE(interviews.score,0),
           COALESCE(interviews.status,'Pending')
    FROM users
    LEFT JOIN submissions ON users.id=submissions.user_id
    LEFT JOIN interviews ON users.id=interviews.candidate_id
    WHERE users.role='candidate'
    """)

    results = cur.fetchall()

    conn.close()

    return render_template("admin_results.html", results=results)


# ===============================
# PROFILE PAGE
# ===============================
@app.route("/profile")
def profile():

    email = session.get("email")   # get logged-in candidate email

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT users.id,
           users.name,
           users.email,
           profiles.phone,
           profiles.college,
           profiles.skills,
           profiles.photo
    FROM users
    LEFT JOIN profiles
    ON users.id = profiles.user_id
    WHERE users.email = ?
    """,(email,))

    data = cur.fetchone()

    conn.close()

    profile = None

    if data:
        profile = {
            "user_id": data[0],
            "name": data[1],
            "email": data[2],
            "phone": data[3],
            "college": data[4],
            "skills": data[5],
            "photo": data[6]
        }

    return render_template("profile.html", profile=profile)
# ===============================
# PROFILE SUMMARY PAGE
# ===============================
@app.route("/profile_summary")
def profile_summary():

    user_id = request.args.get("user_id")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT users.name,
           users.email,
           profiles.phone,
           profiles.college,
           profiles.skills
    FROM users
    LEFT JOIN profiles
    ON users.id = profiles.user_id
    WHERE users.id = ?
    """,(user_id,))

    user = cur.fetchone()

    conn.close()

    return render_template("profile_summary.html", user=user)


# ===============================
# SAVE PROFILE
# ===============================
@app.route("/save_profile", methods=["POST"])
def save_profile():

    phone = request.form.get("phone")
    college = request.form.get("college")
    skills = request.form.get("skills")
    name = request.form.get("name")

    user_id = request.form.get("user_id")

    # ✅ if user_id missing, redirect back to profile
    if not user_id:
        return redirect("/profile")

    user_id = int(user_id)

    photo = request.files.get("photo")
    resume = request.files.get("resume")

    photo_filename = None
    resume_filename = None

    if photo and photo.filename != "":
        photo_filename = photo.filename
        photo.save("static/uploads/" + photo_filename)

    if resume and resume.filename != "":
        resume_filename = resume.filename
        resume.save("static/resumes/" + resume_filename)

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # update name in users table
    cur.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))

    cur.execute("SELECT photo,resume FROM profiles WHERE user_id=?", (user_id,))
    existing = cur.fetchone()

    if existing:

        if not photo_filename:
            photo_filename = existing[0]

        if not resume_filename:
            resume_filename = existing[1]

        cur.execute("""
        UPDATE profiles
        SET phone=?, college=?, skills=?, photo=?, resume=?
        WHERE user_id=?
        """,(phone,college,skills,photo_filename,resume_filename,user_id))

    else:

        cur.execute("""
        INSERT INTO profiles(user_id,phone,college,skills,photo,resume)
        VALUES(?,?,?,?,?,?)
        """,(user_id,phone,college,skills,photo_filename,resume_filename))

    conn.commit()
    conn.close()

    return redirect("/profile_summary?user_id=" + str(user_id))

# View profile (admin)
@app.route("/view_profile/<int:user_id>")
def view_profile(user_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT users.name,
           users.email,
           profiles.phone,
           profiles.college,
           profiles.skills
    FROM users
    LEFT JOIN profiles
    ON users.id = profiles.user_id
    WHERE users.id=?
    """,(user_id,))

    profile = cur.fetchone()

    conn.close()

    return render_template("admin_view_profile.html", profile=profile)
# Open Add Coding Problem Page
@app.route("/add_coding_problem_page")
def add_coding_problem_page():
    return render_template("add_coding_problem.html")


# Save Coding Problem
@app.route("/add_coding_problem", methods=["POST"])
def add_coding_problem():

    title = request.form["title"]
    difficulty = request.form["difficulty"]
    description = request.form["description"]

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # Insert coding problem
    cur.execute(
        "INSERT INTO coding_problems (title,difficulty,description) VALUES (?,?,?)",
        (title, difficulty, description)
    )

    problem_id = cur.lastrowid

    # Save test cases
    for i in range(1, 6):   # up to 5 test cases

        inputs = []

        # collect multiple inputs (max 5 inputs per testcase)
        for j in range(1, 6):
            val = request.form.get(f"input{j}_{i}")
            if val:
                inputs.append(val)

        input_data = "\n".join(inputs)

        output = request.form.get(f"output_{i}")

        if input_data and output:
            cur.execute(
                "INSERT INTO testcases(problem_id,input,output) VALUES (?,?,?)",
                (problem_id, input_data, output)
            )

    conn.commit()
    conn.close()

    return redirect("/add_coding_problem_page?success=1")


@app.route("/delete_coding_problem/<int:problem_id>")
def delete_coding_problem(problem_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # delete testcases
    cur.execute("DELETE FROM testcases WHERE problem_id=?", (problem_id,))

    # delete problem
    cur.execute("DELETE FROM coding_problems WHERE id=?", (problem_id,))

    conn.commit()
    conn.close()

    return redirect("/view_coding_questions")


@app.route("/view_questions")
def view_questions():
    return render_template("view_questions.html")


@app.route("/view_coding_questions")
def view_coding_questions():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id,title,difficulty,description FROM coding_problems")
    problems = cur.fetchall()

    conn.close()

    return render_template("view_coding_questions.html", problems=problems)



# Open Add MCQ Page
@app.route("/add_mcq_page")
def add_mcq_page():
    return render_template("add_mcq.html")


# Save MCQ Question

from flask import flash, redirect, url_for
@app.route('/add_mcq', methods=['GET', 'POST'])
def add_mcq():

    if request.method == 'POST':

        question_number = request.form['question_number']
        question = request.form['question']
        option_a = request.form['option_a']
        option_b = request.form['option_b']
        option_c = request.form['option_c']
        option_d = request.form['option_d']
        answer = request.form['answer']
        domain = request.form['domain']   # ⭐ NEW

        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO mcq_questions
        (question_number, question, option_a, option_b, option_c, option_d, answer, domain)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            question_number,
            question,
            option_a,
            option_b,
            option_c,
            option_d,
            answer,
            domain
        ))

        conn.commit()
        conn.close()

        flash("MCQ Question added successfully!", "success")

        return redirect(url_for('add_mcq'))

    return render_template("add_mcq.html")
# @app.route('/view_mcq')
# def view_mcq():

#     conn = sqlite3.connect('database.db')
#     cursor = conn.cursor()

#     cursor.execute("SELECT * FROM mcq_questions")
#     mcqs = cursor.fetchall()

#     conn.close()

#     return render_template("view_mcq_questions.html", mcqs=mcqs)
@app.route("/view_mcq_questions")
def view_mcq_questions():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT id,question_number,question,
               option_a,option_b,option_c,option_d,answer
        FROM mcq_questions
    """)

    questions = cur.fetchall()

    conn.close()

    return render_template("view_mcq_questions.html", questions=questions)
@app.route("/mcq_test")
def mcq_test():

    # ✅ LOGIN CHECK (IMPORTANT)
    if "email" not in session:
        return redirect("/")

    domain = session.get("domain")

    # ✅ DOMAIN CHECK
    if not domain:
        return "No domain assigned to user"

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM mcq_questions WHERE domain=?",
        (domain,)
    )
    questions = cur.fetchall()

    conn.close()

    return render_template("mcq_test.html", questions=questions)


@app.route("/submit_mcq", methods=["POST"])
def submit_mcq():

    # ✅ LOGIN CHECK
    if "user_id" not in session:
        return redirect("/")

    score = 0
    domain = session.get("domain")
    user_id = session.get("user_id")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # ✅ get only domain questions
    cur.execute(
        "SELECT * FROM mcq_questions WHERE domain=?",
        (domain,)
    )
    questions = cur.fetchall()

    # ================= CHECK ALL ANSWERED =================
    answered_count = 0

    for q in questions:
        user_answer = request.form.get(f"q{q[0]}")
        if user_answer:
            answered_count += 1

    if answered_count < len(questions):
        conn.close()
        return "Please answer all questions before submitting"

    # ================= CALCULATE SCORE =================
    for q in questions:
        user_answer = request.form.get(f"q{q[0]}")
        if user_answer == q[7]:
            score += 1

    # ✅ save in session
    session["mcq_score"] = score

    # ================= SAVE IN DATABASE =================
    try:
        cur.execute("""
        INSERT INTO mcq_results(user_id, score)
        VALUES(?,?)
        ON CONFLICT(user_id) DO UPDATE SET score=excluded.score
        """, (user_id, score))

        conn.commit()

    except Exception as e:
        conn.close()
        return f"Error saving MCQ score: {str(e)}"

    conn.close()

    # ✅ go to coding test
    return redirect("/start_coding_test")

# @app.route("/coding_test")
# def coding_test():

#     domain = session["domain"]

#     conn = sqlite3.connect("database.db")
#     cur = conn.cursor()

#     cur.execute(
#         "SELECT * FROM problems WHERE domain=?",
#         (domain,)
#     )

#     problems = cur.fetchall()

#     conn.close()

#     return render_template("view_coding_questions.html", problems=problems)


@app.route("/delete_mcq/<int:mcq_id>")
def delete_mcq(mcq_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("DELETE FROM mcq_questions WHERE id=?", (mcq_id,))

    conn.commit()
    conn.close()

    return redirect("/view_mcq_questions")



# ===============================
# SAVE AI INTERVIEW RESULT
# ===============================

@app.route("/save_ai_result", methods=["POST"])
def save_ai_result():

    data = request.json

    score = data.get("score")
    answer = data.get("answer")

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "User not logged in"}), 401

    # simple feedback
    if int(score) >= 80:
        feedback = "Excellent communication"
    elif int(score) >= 50:
        feedback = "Good communication"
    else:
        feedback = "Needs improvement"

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO interviews(candidate_id, score, feedback, status)
    VALUES (?, ?, ?, ?)
    """, (user_id, score, feedback, "Completed"))

    conn.commit()
    conn.close()

    return jsonify({"message": "AI result saved"})



# ===============================
# SAVE INTERVIEW VIDEO
# ===============================
import os
from werkzeug.utils import secure_filename

@app.route("/save_interview_video", methods=["POST"])
def save_interview_video():

    email = session.get("email")

    if not email:
        return {"status":"error","message":"User not logged in"}

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return {"status":"error","message":"User not found"}

    user_id = user[0]

    if "video" not in request.files:
        conn.close()
        return {"status":"error","message":"No video uploaded"}

    video = request.files["video"]

    # folder path
    folder = "static/interview_videos"

    if not os.path.exists(folder):
        os.makedirs(folder)

    # safe filename
    filename = secure_filename("interview_" + str(user_id) + ".webm")

    path = os.path.join(folder, filename)

    video.save(path)

    conn.close()

    return {"status":"saved"}

@app.route("/complete_interview", methods=["POST"])
def complete_interview():
    session["interview_completed"] = True
    return {"status": "ok"}


# check-interview
@app.route("/check_ai_unlock")
def check_ai_unlock():

    email = session.get("email")

    if not email:
        return jsonify({"allowed": False})

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # get user id
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return jsonify({"allowed": False})

    user_id = user[0]

    # get coding score from coding_results
    cur.execute("""
        SELECT AVG(score)
FROM coding_results
WHERE user_id=?
    """, (user_id,))

    result = cur.fetchone()

    conn.close()

    score = result[0] if result and result[0] else 0

    if score >= 75:
        return jsonify({"allowed": True})
    else:
        return jsonify({"allowed": False})
    
#  sumbit_interview
@app.route("/submit_interview", methods=["POST"])
def submit_interview():

    email = session.get("email")

    if not email:
        return {"status": "error", "message": "User not logged in"}

    data = request.get_json()

    print("Interview route called")
    print("Data received:", data)

    if not data:
        return {"status": "error", "message": "No data received"}

    status = data.get("status", "completed")   # completed or cheated
    answer_length = data.get("answer_length", 0)

    # communication score based on speaking length
    if answer_length < 50:
        communication_score = 20
    elif answer_length < 150:
        communication_score = 40
    elif answer_length < 300:
        communication_score = 60
    elif answer_length < 500:
        communication_score = 75
    else:
        communication_score = 90

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if user:
        user_id = user[0]

        # check if interview already exists
        cur.execute("SELECT id FROM interviews WHERE candidate_id=?", (user_id,))
        existing = cur.fetchone()

        if existing:
            cur.execute("""
            UPDATE interviews
            SET status=?, score=?
            WHERE candidate_id=?
            """, (status, communication_score, user_id))
        else:
            cur.execute("""
            INSERT INTO interviews (candidate_id, status, score)
            VALUES (?, ?, ?)
            """, (user_id, status, communication_score))

        conn.commit()

    conn.close()

    return {"status": "ok"}

import subprocess
import tempfile
import sys
import subprocess
import tempfile
import sys
import re
@app.route("/run_code", methods=["POST"])
def run_code():

    data = request.json
    code = data.get("code")
    problem_id = data.get("problem_id")
    language = data.get("language", "python")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # ✅ ONE TEST CASE ONLY
    cur.execute(
        "SELECT input, output FROM testcases WHERE problem_id=? LIMIT 1",
        (problem_id,)
    )
    testcase = cur.fetchone()
    conn.close()

    if not testcase:
        return jsonify({"error": "No testcases found"})

    user_input = testcase[0]
    expected_output = testcase[1]

    try:

        # ================= PYTHON =================
        if language == "python":

            try:
                compile(code, "<string>", "exec")
            except SyntaxError as e:
                return jsonify({
                    "error": f"Syntax Error (Line {e.lineno}): {str(e)}"
                })

            with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w") as f:
                f.write(code)
                filename = f.name

            result = subprocess.run(
                [sys.executable, filename],
                input=user_input,
                text=True,
                capture_output=True,
                timeout=5
            )

        # ================= JAVA =================
        elif language == "java":

            import os
            import re

            # ✅ CHECK CLASS NAME
            if "class Main" not in code:
                return jsonify({
                    "error": "Java class name must be 'Main'"
                })

            with tempfile.TemporaryDirectory() as temp_dir:

                java_file = os.path.join(temp_dir, "Main.java")

                # ✅ USE USER CODE DIRECTLY (NO WRAP)
                with open(java_file, "w") as f:
                    f.write(code)

                # compile
                compile_proc = subprocess.run(
                    ["javac", java_file],
                    capture_output=True,
                    text=True
                )

                if compile_proc.stderr:
                    return jsonify({
                        "error": compile_proc.stderr
                    })

                # run
                result = subprocess.run(
                    ["java", "-cp", temp_dir, "Main"],
                    input=user_input,
                    text=True,
                    capture_output=True,
                    timeout=5
                )

        else:
            return jsonify({"error": "Unsupported language"})

        # ================= OUTPUT =================
        if result.stderr:
            return jsonify({"error": result.stderr})

        output = result.stdout.strip()

        return jsonify({
            "results": [{
                "input": user_input,
                "expected": expected_output,
                "output": output,
                "status": "PASS" if output == expected_output else "FAIL"
            }]
        })

    except Exception as e:
        return jsonify({"error": str(e)})
# sudmit
@app.route("/submit_code", methods=["POST"])
def submit_code():

    data = request.json
    code = data.get("code")
    problem_id = data.get("problem_id")
    language = data.get("language", "python")
    user_id = session["user_id"]

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT input, output FROM testcases WHERE problem_id=?",
        (problem_id,)
    )
    testcases = cur.fetchall()

    results = []
    passed = 0

    try:

        # ================= PYTHON =================
        if language == "python":

            try:
                compile(code, "<string>", "exec")
            except SyntaxError as e:
                return jsonify({
                    "error": f"Syntax Error (Line {e.lineno}): {str(e)}"
                })

        # ================= JAVA =================
        elif language == "java":

            if "class Main" not in code:
                return jsonify({
                    "error": "Java class name must be 'Main'"
                })

        else:
            return jsonify({"error": "Unsupported language"})

        # ================= RUN TEST CASES =================
        for t in testcases:

            user_input = t[0]
            expected_output = t[1]

            try:

                # -------- PYTHON --------
                if language == "python":

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w") as f:
                        f.write(code)
                        filename = f.name

                    result = subprocess.run(
                        [sys.executable, filename],
                        input=user_input,
                        text=True,
                        capture_output=True,
                        timeout=5
                    )

                # -------- JAVA --------
                elif language == "java":

                    import os

                    with tempfile.TemporaryDirectory() as temp_dir:

                        java_file = os.path.join(temp_dir, "Main.java")

                        # ✅ USE USER CODE DIRECTLY (NO WRAP)
                        with open(java_file, "w") as f:
                            f.write(code)

                        # compile
                        compile_proc = subprocess.run(
                            ["javac", java_file],
                            capture_output=True,
                            text=True
                        )

                        if compile_proc.stderr:
                            results.append({
                                "input": user_input,
                                "expected": expected_output,
                                "output": compile_proc.stderr.strip(),
                                "status": "ERROR"
                            })
                            continue

                        # run
                        result = subprocess.run(
                            ["java", "-cp", temp_dir, "Main"],
                            input=user_input,
                            text=True,
                            capture_output=True,
                            timeout=5
                        )

                # -------- COMMON RESULT --------
                if result.stderr:
                    output = result.stderr.strip()
                    status = "ERROR"
                else:
                    output = result.stdout.strip()
                    status = "PASS" if output == expected_output else "FAIL"

                if status == "PASS":
                    passed += 1

                results.append({
                    "input": user_input,
                    "expected": expected_output,
                    "output": output,
                    "status": status
                })

            except Exception as e:
                results.append({
                    "input": user_input,
                    "expected": expected_output,
                    "output": str(e),
                    "status": "ERROR"
                })

        # ================= SCORE =================
        total = len(testcases)
        score = int((passed / total) * 100) if total > 0 else 0

        # ================= SAVE =================
        cur.execute("""
        INSERT INTO coding_results(user_id, problem_id, score)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, problem_id)
        DO UPDATE SET score=excluded.score
        """, (user_id, problem_id, score))

        conn.commit()
        conn.close()

        return jsonify({
            "results": results,
            "score": score,
            "passed": passed,
            "total": total
        })

    except Exception as e:
        return jsonify({"error": str(e)})
@app.route("/start_exam")
def start_exam():

    user_id = session["user_id"]
    domain = session["domain"]

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT * FROM mcq_questions
    WHERE domain=?
    ORDER BY RANDOM()
    LIMIT 15
    """,(domain,))

    mcq = cur.fetchall()

    cur.execute("""
    SELECT * FROM coding_problems
    WHERE domain=?
    ORDER BY RANDOM()
    LIMIT 2
    """,(domain,))

    coding = cur.fetchall()

    conn.close()

    return render_template(
        "view_questions.html",
        mcq=mcq,
        coding=coding
    )

if __name__ == "__main__":
    app.run(debug=True)