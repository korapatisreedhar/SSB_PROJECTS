from flask import Flask, request, jsonify, render_template, redirect, session
from flask_jwt_extended import JWTManager
from auth import register_user, login_user
from database import init_db
import sqlite3

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

    response = login_user(data)

    if "role" in response.json:
        session["email"] = data["email"]

    return response

# DASHBOARD PAGE
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


# interview
@app.route("/coding_editor")
def coding_editor():
    return render_template("coding_editor.html")


# Coding Assessment Page
@app.route("/coding_assessment")
def coding_assessment():
    return render_template("coding_editor.html")


@app.route("/video_interview")
def video_interview():
    return render_template("video_interview.html")


@app.route("/results")
def results():
    return "Interview Results Page"


@app.route("/performance")
def performance():

    email = session.get("email")

    if not email:
        return redirect("/")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return redirect("/dashboard")

    user_id = user[0]

    # Coding score
    cur.execute("SELECT score FROM submissions WHERE user_id=?", (user_id,))
    coding = cur.fetchone()
    coding_score = coding[0] if coding else 0

    # AI interview score
    cur.execute("SELECT score FROM interviews WHERE candidate_id=?", (user_id,))
    interview = cur.fetchone()
    interview_score = interview[0] if interview else 0

    overall = int((coding_score + interview_score) / 2)

    conn.close()

    return render_template(
        "performance.html",
        coding_score=coding_score,
        interview_score=interview_score,
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
        COALESCE(interviews.status,'Pending')
    FROM users
    LEFT JOIN submissions ON users.id=submissions.user_id
    LEFT JOIN interviews ON users.id=interviews.candidate_id
    WHERE users.role='candidate'
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
    cur.execute("SELECT id,name,email,role FROM users")

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


# Add Problem
@app.route("/add_problem", methods=["POST"])
def add_problem():

    data = request.json

    title = data.get("title")
    description = data.get("description")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO problems (title, description) VALUES (?, ?)",
        (title, description)
    )

    problem_id =cur.lastrowid

    conn.commit()
    conn.close()

    return jsonify({"message": "Problem added successfully"})


# Delete Problem
@app.route("/delete_problem/<int:problem_id>")
def delete_problem(problem_id):

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("DELETE FROM problems WHERE id=?", (problem_id,))
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

    return redirect("/admin_coding_judge")


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
@app.route("/save_interview_video", methods=["POST"])
def save_interview_video():

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        return "User not found"

    user_id = user[0]

    video = request.files["video"]

    filename = "interview_" + str(user_id) + ".webm"

    path = "static/interviews/" + filename

    video.save(path)

    cur.execute("""
    INSERT INTO interviews(candidate_id, recording)
    VALUES(?,?)
    """,(user_id, path))

    conn.commit()
    conn.close()

    return "Video Saved"


@app.route("/complete_interview", methods=["POST"])
def complete_interview():
    session["interview_completed"] = True
    return {"status": "ok"}


# check-interview
@app.route("/check_interview")
def check_interview():

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if not user:
        return jsonify({"completed": False})

    user_id = user[0]

    cur.execute("SELECT * FROM interviews WHERE candidate_id=?", (user_id,))
    interview = cur.fetchone()

    conn.close()

    return jsonify({"completed": True if interview else False})
#  sumbit_interview
@app.route("/submit_interview", methods=["POST"])
def submit_interview():

    email = session.get("email")

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    user = cur.fetchone()

    if user:
        user_id = user[0]

        cur.execute("""
        INSERT INTO interviews (candidate_id, status)
        VALUES (?, ?)
        """, (user_id, "completed"))

        conn.commit()

    conn.close()

    return {"status": "ok"}



if __name__ == "__main__":
    app.run(debug=True)