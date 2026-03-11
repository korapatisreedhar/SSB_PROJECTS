import sqlite3
import bcrypt
from flask import jsonify, session
from flask_jwt_extended import create_access_token


def register_user(data):

    name = data["name"]
    email = data["email"]
    password = data["password"]
    role = data.get("role", "candidate")

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
        (name, email, hashed, role)
    )

    conn.commit()
    conn.close()

    return jsonify({"msg": "User registered"})


def login_user(data):

    email = data["email"]
    password = data["password"]

    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT id,password,role FROM users WHERE email=?",
        (email,)
    )

    user = cur.fetchone()

    conn.close()

    if not user:
        return jsonify({"msg": "Invalid Credentials"})

    user_id, hashed, role = user

    # Ensure hashed password is bytes
    if isinstance(hashed, str):
        hashed = hashed.encode()

    if bcrypt.checkpw(password.encode(), hashed):

        # store login user in session
        session["email"] = email
        session["user_id"] = user_id

        token = create_access_token(identity={"id": user_id, "role": role})

        return jsonify({
            "msg": "Login success",
            "token": token,
            "role": role
        })

    return jsonify({"msg": "Invalid Credentials"})