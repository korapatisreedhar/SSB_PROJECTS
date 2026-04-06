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
    user_id = session.get("user_id")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT name FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    name = user[0] if user else "Candidate"

    cur.execute("SELECT score FROM mcq_results WHERE user_id=?", (user_id,))
    mcq_done = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM coding_results WHERE user_id=?", (user_id,))
    coding_count = cur.fetchone()[0]

    conn.close()

    test_completed = True if (mcq_done and coding_count >= 2) else False

    # 🔥 ADD THIS BEFORE RETURN
    cur = sqlite3.connect("database.db").cursor()
    cur.execute("SELECT cheated FROM users WHERE email=?", (email,))
    cheated = cur.fetchone()[0]

    return render_template(
    "dashboard.html",
    name=name,
    test_completed=test_completed,
    cheated=cheated   # 🔥 ADD THIS
)
@app.route("/start_coding_test")
def start_coding_test():
    if session.get("blocked"):
        return "<h2 style='text-align:center;margin-top:100px;  '>❌ Disqualified due to cheating</h2>"

    if "email" not in session:
        return redirect("/")

    user_id = session.get("user_id")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM coding_results WHERE user_id=?", (user_id,))
    coding_count = cur.fetchone()[0]

    if coding_count >= 2:
        conn.close()
        return "<h2 style='text-align:center;margin-top:100px;'>✅ Your test is already submitted</h2>"

    if "mcq_score" not in session:
        conn.close()
        return redirect("/mcq_test")

    cur.execute("SELECT id FROM coding_problems")
    problems = cur.fetchall()

    conn.close()

    if len(problems) < 2:
        return "Not enough coding questions added by admin."

    selected = random.sample(problems, 2)

    session["coding_questions"] = [p[0] for p in selected]
    session["current_index"] = 0
    session["total_questions"] = len(selected)

    return redirect(f"/coding_editor/{session['coding_questions'][0]}")

# interview
@app.route("/coding_editor")
@app.route("/coding_editor/<int:problem_id>")
def coding_editor(problem_id=None):
    if session.get("blocked"):
        return "<h2 style='text-align:center;margin-top:100px;'>❌ Disqualified due to cheating</h2>"

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
    
@app.route("/final_results")
def final_results():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT 
        u.id,
        u.name,
        u.email,
        IFNULL(AVG(c.score), 0),
        IFNULL(m.score, 0),
        IFNULL(i.score, 0),
        IFNULL(u.cheated, 0),
        IFNULL(u.override_status, '')
    FROM users u
    LEFT JOIN coding_results c ON u.id = c.user_id
    LEFT JOIN mcq_results m ON u.id = m.user_id
    LEFT JOIN (
    SELECT * FROM interviews
    WHERE id IN (
        SELECT MAX(id) FROM interviews GROUP BY candidate_id
    )
) i ON u.id = i.candidate_id
    WHERE u.role='candidate'
    GROUP BY u.id
    """)

    data = cur.fetchall()
    conn.close()

    temp = []

    for row in data:
        user_id, name, email, coding, mcq, interview, cheated, override = row

        total_mcq = 18

        mcq_percentage = min((mcq / total_mcq) * 100 if total_mcq else 0, 100)
        coding_percentage = min(coding, 100)
        interview_percentage = min(interview, 100)

        overall = int(
            (mcq_percentage * 0.4) +
            (coding_percentage * 0.4) +
            (interview_percentage * 0.2)
        )

        # ✅ FINAL STATUS
        # ✅ ADMIN OVERRIDE FIRST PRIORITY
        if override:
            status = override

        elif cheated == 1:
            status = "Rejected"

        elif mcq == 0 and coding == 0 and interview == 0:
            status = "Pending"

        elif overall >= 75:
            status = "Selected"

        elif overall >= 50:
            status = "On Hold"

        else:
            status = "Rejected"

        temp.append({
            "id": user_id,
            "name": name,
            "email": email,
            "coding": int(coding_percentage),
            "mcq": int(mcq_percentage),
            "interview": int(interview_percentage),
            "overall": overall,
            "status": status,
            "cheated": cheated
        })

    # ✅ SORT BY OVERALL
    temp.sort(key=lambda x: x["overall"], reverse=True)

    results = []
    rank = 1

    for r in temp:
        results.append((
            rank,
            r["id"],
            r["name"],
            r["email"],
            r["coding"],
            r["mcq"],
            r["interview"],
            r["overall"],
            r["status"],
            r["cheated"]
        ))
        rank += 1

    return render_template("final_results.html", results=results)

@app.route("/finish_test")
def finish_test():

    session.pop("coding_questions", None)
    session.pop("current_index", None)
    session.pop("total_questions", None)

    return redirect("/performance")   # ✅ CHANGE HERE

@app.route("/final_submit")
def final_submit():

    # optional logic
    return redirect("/performance")



@app.route("/video_interview")
def video_interview():

    if "email" not in session:
        return redirect("/")

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return redirect("/")

    user_id = user[0]

    cur.execute("""
        SELECT score FROM interviews
        WHERE candidate_id=?
        ORDER BY id DESC LIMIT 1
    """, (user_id,))

    data = cur.fetchone()

    # 🔥 MAIN FIX
    if data and data[0] > 0:
        conn.close()
        return redirect("/dashboard?msg=already_attended")

    conn.close()

    return render_template("video_interview.html")




@app.route("/performance")
def performance():

    if "email" not in session:
        return redirect("/")

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # USER
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        return "User not found"

    user_id = user[0]

    # CHEATING
    cur.execute("SELECT cheated FROM users WHERE id=?", (user_id,))
    cheated = cur.fetchone()[0]

    # CODING (AVG)
    cur.execute("SELECT AVG(score) FROM coding_results WHERE user_id=?", (user_id,))
    coding_score = cur.fetchone()[0] or 0

    # MCQ
    cur.execute("SELECT score FROM mcq_results WHERE user_id=?", (user_id,))
    mcq = cur.fetchone()
    mcq_score = mcq[0] if mcq else 0

    domain = session.get("domain")

    cur.execute("SELECT COUNT(*) FROM mcq_questions WHERE domain=?", (domain,))
    total_mcq = cur.fetchone()[0]

    mcq_percentage = min((mcq_score / total_mcq) * 100 if total_mcq else 0, 100)

    # 🔥 FIXED INTERVIEW QUERY (ONLY CHANGE)
    cur.execute("""
        SELECT score FROM interviews
        WHERE candidate_id=?
        ORDER BY id DESC LIMIT 1
    """, (user_id,))
    
    interview = cur.fetchone()
    interview_score = interview[0] if interview else 0

    # OVERALL
    overall = int(
        (mcq_percentage * 0.4) +
        (coding_score * 0.4) +
        (interview_score * 0.2)
    )

    # ✅ STATUS (OPTIONAL IMPROVED)
    if cheated == 1:
        status = "Rejected"

    elif interview_score == 0:   # 🔥 better condition
        status = "Pending"

    elif overall >= 75:
        status = "Selected"

    elif overall >= 50:
        status = "On Hold"

    else:
        status = "Rejected"

    conn.close()

    return render_template(
        "performance.html",
        coding_score=int(coding_score),
        mcq_score=int(mcq_percentage),
        interview_score=int(interview_score),
        overall=overall,
        status=status,
        disqualified=cheated
    )



@app.route("/update_status", methods=["POST"])
def update_status():
    user_id = request.form.get("user_id")
    action = request.form.get("action")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    if action == "Selected":
        cur.execute("UPDATE users SET override_status='Selected' WHERE id=?", (user_id,))
    elif action == "Rejected":
        cur.execute("UPDATE users SET override_status='Rejected' WHERE id=?", (user_id,))
    elif action == "On Hold":
        cur.execute("UPDATE users SET override_status='On Hold' WHERE id=?", (user_id,))

    conn.commit()
    conn.close()

    return redirect("/final_results")



@app.route("/admin_dashboard")
def admin_dashboard():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users WHERE role='candidate'")
    total_candidates = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM submissions")
    coding_tests = cur.fetchone()[0]

    cur.execute("""
    SELECT COUNT(DISTINCT candidate_id)
FROM interviews
WHERE candidate_id IN (
    SELECT id FROM users WHERE role='candidate'
)
""")
    ai_interviews = cur.fetchone()[0]

    cur.execute("""
    SELECT 
    u.id,
    u.name,
    u.email,
    IFNULL(AVG(c.score), 0),
    IFNULL(m.score, 0),
    IFNULL(i.score, 0),
    IFNULL(i.recording, ''),   -- ✅ ADD THIS
    IFNULL(u.cheated, 0),
    IFNULL(u.override_status, '')
FROM users u
LEFT JOIN coding_results c ON u.id = c.user_id
LEFT JOIN mcq_results m ON u.id = m.user_id
LEFT JOIN (
    SELECT * FROM interviews
    WHERE id IN (
        SELECT MAX(id) FROM interviews GROUP BY candidate_id
    )
) i ON u.id = i.candidate_id
WHERE u.role='candidate'
GROUP BY u.id
    """)

    data = cur.fetchall()

    selected = rejected = onhold = pending = 0
    candidates = []

    for row in data:
        user_id, name, email, coding, mcq, interview, video, cheated, override = row

        total_mcq = 18

        mcq_percentage = min((mcq / total_mcq) * 100 if total_mcq else 0, 100)
        coding_percentage = min(coding, 100)
        interview_percentage = min(interview, 100)

        # 🔥 CHEATING LOGIC (TOP PRIORITY)
        if cheated == 1:
            status = "Rejected"
            mcq_percentage = 0
            coding_percentage = 0
            interview_percentage = 0

        # 🔥 ADMIN OVERRIDE
        elif override:
            status = override

        # 🔥 PENDING IF ANY SECTION NOT DONE
        elif mcq_percentage == 0 or coding_percentage == 0 or interview_percentage == 0:
            status = "Pending"

        else:
            overall = int(
                (mcq_percentage * 0.4) +
                (coding_percentage * 0.4) +
                (interview_percentage * 0.2)
            )

            if overall >= 75:
                status = "Selected"
            elif overall >= 50:
                status = "On Hold"
            else:
                status = "Rejected"

        # COUNTS
        if status == "Selected":
            selected += 1
        elif status == "Rejected":
            rejected += 1
        elif status == "On Hold":
            onhold += 1
        else:
            pending += 1

        candidates.append((
    name,
    email,
    int(coding_percentage),
    int(mcq_percentage),
    int(interview_percentage),
    "Completed" if interview_percentage > 0 else "Pending",  # interview status
    status,   # final result
    video,
    "Yes" if cheated else "No"
))

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_candidates=total_candidates,
        coding_tests=coding_tests,
        ai_interviews=ai_interviews,

        selected_candidates=selected,
        rejected_candidates=rejected,
        onhold_candidates=onhold,
        pending_candidates=pending,

        candidates=candidates[:5]
    )




@app.route("/reset_cheating/<int:user_id>")
def reset_cheating(user_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # ✅ RESET CHEATING FLAG
    cur.execute("UPDATE users SET cheated=0 WHERE id=?", (user_id,))

    # ✅ DELETE MCQ RESULT
    cur.execute("DELETE FROM mcq_results WHERE user_id=?", (user_id,))

    # ✅ DELETE CODING RESULTS
    cur.execute("DELETE FROM coding_results WHERE user_id=?", (user_id,))

    # ✅ DELETE INTERVIEW DATA
    cur.execute("DELETE FROM interviews WHERE candidate_id=?", (user_id,))

    conn.commit()
    conn.close()

    return redirect("/final_results")

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
    SELECT u.id,
           u.name,
           u.email,

           IFNULL(AVG(c.score), 0) as coding_score,
           IFNULL(AVG(i.score), 0) as interview_score,
           IFNULL(m.score, 0) as mcq_score

    FROM users u

    LEFT JOIN coding_results c ON u.id = c.user_id
    LEFT JOIN interviews i ON u.id = i.candidate_id
    LEFT JOIN mcq_results m ON u.id = m.user_id

    WHERE u.role = 'candidate'

    GROUP BY u.id
    """)

    data = cur.fetchall()
    conn.close()

    results = []

    for row in data:
        user_id, name, email, coding, interview, mcq = row

        # ✅ MCQ → percentage
        mcq_percent = (mcq / 18) * 100 if mcq else 0

        # ✅ final score (60% MCQ + 40% coding)
        overall = int((mcq_percent * 0.6) + (coding * 0.4))

        # ✅ status
        status = "Completed" if (mcq > 0 and coding > 0) else "Pending"

        results.append((name, email, int(coding), int(interview), overall, status))

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

    # ✅ optional login check (recommended)
    if "email" not in session:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # ✅ ADD domain column
    cur.execute("""
        SELECT id,question_number,question,
               option_a,option_b,option_c,option_d,answer,domain
        FROM mcq_questions
    """)

    questions = cur.fetchall()

    conn.close()

    return render_template("view_mcq_questions.html", questions=questions)
@app.route("/mcq_test")
def mcq_test():

    if "email" not in session:
        return redirect("/")

    user_id = session.get("user_id")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # 🔒 BLOCK REATTEMPT (IMPORTANT)
    cur.execute("SELECT score FROM mcq_results WHERE user_id=?", (user_id,))
    mcq_done = cur.fetchone()

    if mcq_done:
        conn.close()
        return "<h2 style='text-align:center;margin-top:100px;'>❌ You already attempted the exam</h2>"

    # DOMAIN LOGIC
    domain = session.get("domain")

    if not domain:
        conn.close()
        return "No domain assigned to user"

    domain = domain.strip()

    cur.execute(
        "SELECT * FROM mcq_questions WHERE LOWER(domain)=LOWER(?)",
        (domain,)
    )

    questions = cur.fetchall()
    conn.close()

    if not questions:
        return f"No MCQ questions found for domain: {domain}"

    return render_template("mcq_test.html", questions=questions)
    
    


@app.route("/submit_mcq", methods=["POST"])
def submit_mcq():

    if "user_id" not in session:
        return redirect("/")

    user_id = session.get("user_id")
    domain = session.get("domain")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # 🔥 BLOCK IF CHEATED
    if session.get("blocked"):
        cur.execute("UPDATE users SET cheated=1 WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        return "<h2 style='text-align:center;margin-top:100px;'>❌ Disqualified due to cheating</h2>"

    # GET QUESTIONS
    cur.execute("SELECT * FROM mcq_questions WHERE domain=?", (domain,))
    questions = cur.fetchall()

    # ✅ CALCULATE SCORE (NO STRICT VALIDATION)
    score = 0
    for q in questions:
        user_answer = request.form.get(f"q{q[0]}")
        if user_answer and user_answer == q[7]:
            score += 1

    # ✅ CHEATING FLAG
    cheated = 1 if session.get("violations", 0) >= 3 else 0

    # ✅ SAVE SESSION (VERY IMPORTANT)
    session["mcq_score"] = score

    # ✅ SAVE DB
    cur.execute("""
    INSERT INTO mcq_results(user_id, score, cheated)
    VALUES(?,?,?)
    ON CONFLICT(user_id)
    DO UPDATE SET score=excluded.score, cheated=excluded.cheated
    """, (user_id, score, cheated))

    conn.commit()
    conn.close()

    # 🔥 RESET SESSION FLAGS
    session.pop("violations", None)
    session.pop("blocked", None)

    return redirect("/start_coding_test")

@app.route("/edit_mcq/<int:mcq_id>", methods=["GET", "POST"])
def edit_mcq(mcq_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    if request.method == "POST":

        question = request.form["question"]
        option_a = request.form["option_a"]
        option_b = request.form["option_b"]
        option_c = request.form["option_c"]
        option_d = request.form["option_d"]
        answer = request.form["answer"]

        cur.execute("""
        UPDATE mcq_questions
        SET question=?, option_a=?, option_b=?, option_c=?, option_d=?, answer=?
        WHERE id=?
        """, (question, option_a, option_b, option_c, option_d, answer, mcq_id))

        conn.commit()
        conn.close()

        return redirect("/view_mcq_questions")

    # GET request
    cur.execute("SELECT * FROM mcq_questions WHERE id=?", (mcq_id,))
    question = cur.fetchone()
    conn.close()

    return render_template("edit_mcq.html", q=question)
@app.route("/delete_mcq/<int:mcq_id>")
def delete_mcq(mcq_id):

    # ✅ login check (optional but recommended)
    if "email" not in session:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    try:
        # ✅ check if question exists
        cur.execute("SELECT id FROM mcq_questions WHERE id=?", (mcq_id,))
        data = cur.fetchone()

        if not data:
            conn.close()
            return "Question not found"

        # ✅ delete
        cur.execute("DELETE FROM mcq_questions WHERE id=?", (mcq_id,))
        conn.commit()

    except Exception as e:
        conn.close()
        return f"Error deleting question: {str(e)}"

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

    # ✅ ADD THIS BLOCK (NEW)
    cur.execute("SELECT id FROM interviews WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE interviews
            SET score=?, feedback=?, status=?
            WHERE candidate_id=?
        """, (score, feedback, "Completed", user_id))
    else:
        # 👇 your old insert (UNCHANGED)
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

    folder = "static/interview_videos"
    if not os.path.exists(folder):
        os.makedirs(folder)

    filename = secure_filename(f"interview_{user_id}.webm")
    full_path = os.path.join(folder, filename)

    video.save(full_path)

    # ✅ SAVE PATH (IMPORTANT)
    video_path = f"interview_videos/{filename}"

    # ✅ ADD THIS BLOCK (NEW SAFETY)
    cur.execute("SELECT id FROM interviews WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE interviews
            SET recording=?
            WHERE candidate_id=?
        """, (video_path, user_id))
    else:
        cur.execute("""
            INSERT INTO interviews (candidate_id, recording)
            VALUES (?,?)
        """, (user_id, video_path))

    conn.commit()
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

    if not data:
        return {"status": "error", "message": "No data received"}

    raw_status = data.get("status", "completed")

    if str(raw_status).lower() == "cheated":
        status = "Cheated"
    else:
        status = "Completed"

    answer_length = data.get("answer_length", 0)

    # score logic
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

        # 🔥 ADD THIS BLOCK (MAIN FIX)
        cur.execute("""
        SELECT score FROM interviews
        WHERE candidate_id=?
        ORDER BY id DESC LIMIT 1
        """, (user_id,))
        already = cur.fetchone()

        if already and already[0] > 0:
            conn.close()
            return {"status": "error", "message": "Interview already submitted"}

        # 🔥 YOUR OLD LOGIC (UNCHANGED)
        cur.execute("SELECT id FROM interviews WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (user_id,))
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

        # cheating flag
        if status == "Cheated":
            cur.execute("UPDATE users SET cheated=1 WHERE id=?", (user_id,))

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

    # 🔥 FIX: SAVE CODING CHEATING TO DB
    if session.get("blocked"):

        conn = sqlite3.connect("database.db")
        cur = conn.cursor()

        cur.execute("UPDATE users SET cheated=1 WHERE id=?", (session["user_id"],))

        conn.commit()
        conn.close()

        return jsonify({"error": "❌ Disqualified due to cheating"})

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
@app.route('/log_violation', methods=['POST'])
def log_violation():

    if "user_id" not in session:
        return jsonify({"status": "no user"})

    data = request.json
    reason = data.get("reason")

    if "violations" not in session:
        session["violations"] = 0

    session["violations"] += 1

    # 🔥 ADD THIS (MAIN FIX)
    if session["violations"] >= 3:
        session["blocked"] = True

        conn = sqlite3.connect("database.db")
        cur = conn.cursor()
        cur.execute("UPDATE users SET cheated=1 WHERE id=?", (session["user_id"],))
        conn.commit()
        conn.close()

    print(f"[CHEAT] User:{session['user_id']} | {reason} | Count:{session['violations']}")

    return jsonify({"status": "logged"})

@app.route("/view_selected")
def view_selected():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT name, email FROM users
    WHERE override_status='Selected'
    """)

    data = cur.fetchall()
    conn.close()

    return render_template("view_selected.html", data=data)





@app.route("/view_rejected")
def view_rejected():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT name, email FROM users
    WHERE override_status='Rejected' OR cheated=1
    """)

    data = cur.fetchall()
    conn.close()

    return render_template("view_rejected.html", data=data)


@app.route("/view_status")
def view_status():

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    SELECT 
        u.name,
        u.email,
        IFNULL(m.score, 0),
        IFNULL(AVG(c.score), 0),
        IFNULL(i.score, 0),
        u.cheated,
        u.override_status
    FROM users u
    LEFT JOIN mcq_results m ON u.id = m.user_id
    LEFT JOIN coding_results c ON u.id = c.user_id
    LEFT JOIN (
        SELECT * FROM interviews
        WHERE id IN (
            SELECT MAX(id) FROM interviews GROUP BY candidate_id
        )
    ) i ON u.id = i.candidate_id
    WHERE u.role='candidate'
    GROUP BY u.id
    """)

    data = cur.fetchall()
    conn.close()

    final_data = []

    for row in data:
        name, email, mcq, coding, interview, cheated, override = row

        mcq_per = min((mcq/15)*100 if mcq else 0, 100)
        coding_per = min(coding, 100)
        interview_per = min(interview, 100)

        # STATUS LOGIC
        if cheated == 1:
            status = "Cheated"
        elif override:
            status = override
        elif mcq == 0 or coding == 0 or interview == 0:
            status = "Pending"
        else:
            overall = int((mcq_per*0.4)+(coding_per*0.4)+(interview_per*0.2))
            if overall >= 75:
                status = "Selected"
            elif overall >= 50:
                status = "On Hold"
            else:
                status = "Rejected"

        final_data.append((name, email, mcq_per, coding_per, interview_per, status))

    return render_template("view_status.html", data=final_data)




import smtplib
from email.mime.text import MIMEText
from flask import redirect, url_for
import smtplib
from email.mime.text import MIMEText

@app.route("/send_mail/<email>/<status>")
def send_mail_route(email, status):

    sender_email = "korapatisreedhar9999@gmail.com"
    password = "puqm qfqj qdua ebtm"   # Gmail App Password

    # ===============================
    # PROFESSIONAL HTML EMAIL
    # ===============================
    if status == "Selected":
        subject = "Offer Confirmation – Congratulations 🎉"

        body = f"""
        <html>
        <body style="font-family:Segoe UI;">

        <h2 style="color:#1e3c72;">SSB Training & Placement Pvt Ltd</h2>

        <p>Dear Candidate,</p>

        <p>
        We are delighted to inform you that you have been 
        <b style="color:green;">SELECTED</b> for the opportunity at our organization.
        </p>

        <p>
        Your performance throughout the selection process has been exceptional, 
        and we truly appreciate your effort and dedication.
        </p>

        <p>
        Our HR team will contact you shortly with further details regarding onboarding.
        </p>

        <p>
        We look forward to welcoming you to our team.
        </p>

        <br>

        <p><b>Best Regards,</b><br>
        HR Team<br>
        SSB Training and Placement Pvt Ltd</p>

        <hr>
        <small>This is an automated email. Please do not reply.</small>

        </body>
        </html>
        """

    else:
        subject = "Application Status Update"

        body = f"""
        <html>
        <body style="font-family:Segoe UI;">

        <h2 style="color:#1e3c72;">SSB Training & Placement Pvt Ltd</h2>

        <p>Dear Candidate,</p>

        <p>
        Thank you for your interest in our organization and for participating in the recruitment process.
        </p>

        <p>
        After careful consideration, we regret to inform you that you have not been selected at this time.
        </p>

        <p>
        We encourage you to apply for future opportunities that match your skills and experience.
        </p>

        <p>
        We wish you success in your career journey.
        </p>

        <br>

        <p><b>Best Regards,</b><br>
        HR Team<br>
        SSB Training and Placement Pvt Ltd</p>

        <hr>
        <small>This is an automated email. Please do not reply.</small>

        </body>
        </html>
        """

    # ===============================
    # EMAIL SETUP
    # ===============================
    msg = MIMEText(body, "html")   # IMPORTANT: HTML email
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = email

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, email, msg.as_string())
        server.quit()

        # ✅ SUCCESS PAGE WITH BUTTON
        return """
        <div style="display:flex;justify-content:center;align-items:center;height:80vh;
                    background:linear-gradient(135deg,#1e3c72,#2a5298);">

            <div style="background:white;padding:40px;border-radius:12px;
                        text-align:center;box-shadow:0 8px 25px rgba(0,0,0,0.3);">

                <h2 style="color:green;">✅ Email Sent Successfully</h2>
                <br>

                <a href="/admin_dashboard"
                   style="background:#1e3c72;color:white;padding:10px 20px;
                          border-radius:6px;text-decoration:none;">
                    ⬅ Go to Dashboard
                </a>

            </div>

        </div>
        """

    except Exception as e:
        return f"<h3 style='color:red;'>Error: {str(e)}</h3>"

if __name__ == "__main__":
    app.run(debug=True)