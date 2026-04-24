from flask import Flask,jsonify,request
from flask_cors import CORS
import sqlite3
from werkzeug.security import generate_password_hash,check_password_hash
from flask_jwt_extended import JWTManager,create_access_token,get_jwt_identity,jwt_required
import os
from dotenv import load_dotenv
import uuid
import requests

load_dotenv()

app = Flask(__name__)
CORS(app)

app.config["JWT_SECRET_KEY"] = "shazai_backend_super_secret_key_998877665544332211_secure"
jwt = JWTManager(app)

def get_connect():
  return sqlite3.connect("database.db")

def create_table():
  conn = get_connect()
  conn.execute("""CREATE TABLE IF NOT EXISTS users(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT NOT NULL,
               phone TEXT NOT NULL,
               password TEXT NOT NULL
               )""")
  conn.execute("""CREATE TABLE IF NOT EXISTS agent(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL,
               session_id TEXT NOT NULL,
               role TEXT NOT NULL,
               message TEXT NOT NULL,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY (user_id) REFERENCES users(id)
               )""")
  conn.commit()
  conn.close()
create_table()

@app.route("/api/signup",methods=["POST"])
def signup():
  data = request.get_json()
  username = data.get("username")
  phone = data.get("phone")
  password = data.get("password")
  if not username or not phone or not password:
    return jsonify({"error":"All fields are mandatory"}),400
  hash_password = generate_password_hash(password)
  conn = get_connect()
  cursor = conn.execute("SELECT username FROM users WHERE username = ?",(username,))
  user_name = cursor.fetchone()
  if user_name:
    conn.close()
    return jsonify({"error":"Username Already Exists"}),401
  
  cursor = conn.execute("SELECT phone FROM users WHERE phone = ?",(phone,))
  phone_exist = cursor.fetchone()
  if phone_exist:
    conn.close()
    return jsonify({"error":"Phone Number Already Exists"}),401
  conn.execute("INSERT INTO users(username,phone,password) VALUES(?,?,?)",(username,phone,hash_password))
  conn.commit()
  conn.close()
  return jsonify({"message":"User Registered Successfully"}),200

@app.route("/api/login",methods=["POST"])
def login():
  data = request.get_json()
  username = data.get("username")
  password = data.get("password")
  if not username or not password:
    return jsonify({"error":"All fields are mandatory"}),400
  conn = get_connect()
  cursor = conn.execute("SELECT id,password FROM users WHERE username = ?",(username,))
  user = cursor.fetchone()
  if not user:
    conn.close()
    return jsonify({"error":"User Not Found"}),401
  if not check_password_hash(user[1],password):
    conn.close()
    return jsonify({"error":"Invalid Password"}),401
  access_token = create_access_token(identity=str(user[0]))
  return jsonify({"message":"Login Sucessfully","access_token":access_token}),200

@app.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    user_id = get_jwt_identity()
    data = request.get_json()
    message = data.get("message")
    session_id = data.get("session") or str(uuid.uuid4())

    conn = get_connect()
    
    # User message save karein
    conn.execute("INSERT INTO agent(user_id,role,message,session_id) VALUES(?,?,?,?)",(user_id,"user",message,session_id))
    conn.commit()

    # Gemini API Key (Render settings se uthayega)
    api_key = os.getenv("GEMINI_API_KEY")

    # Gemini Direct API Format
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{"text": message}]
        }]
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        ai_data = response.json()

        # Gemini ka response structure OpenRouter se alag hota hai
        if "candidates" in ai_data:
            ai_reply = ai_data["candidates"][0]["content"]["parts"][0]["text"]
            
            # AI reply save karein
            conn.execute("INSERT INTO agent(user_id,role,message,session_id) VALUES(?,?,?,?)",(user_id,"assistant",ai_reply,session_id))
            conn.commit()
            
            return jsonify({"reply": ai_reply, "session_id": session_id}), 200
        else:
            print("Gemini Error:", ai_data)
            return jsonify({"error": "Gemini API Error", "details": ai_data}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
  
@app.route("/api/session",methods=["GET"])
@jwt_required()
def session():
  user_id = get_jwt_identity()
  conn = get_connect()
  cursor = conn.execute("""SELECT session_id, message 
                        FROM agent WHERE role = "user" AND user_id = ?
                        GROUP BY session_id 
                        ORDER BY created_at DESC
                        """,(user_id,))
  sessions = cursor.fetchall()
  conn.close()
  side_history = []
  for s in sessions:
    title = s[1][:15] + "..." if len(s[1]) > 15 else s[1]
    side_history.append({
      "session_id":s[0],
      "title":title
    })
  return jsonify(side_history), 200

@app.route("/api/history/<session_id>",methods=["GET"])
@jwt_required()
def sidechat(session_id):
  user_id = get_jwt_identity()
  conn = get_connect()
  cursor = conn.execute("""SELECT role,message 
               FROM agent 
               WHERE session_id=? AND user_id=? 
               ORDER BY created_at ASC
               """,(session_id,user_id))
  messages = cursor.fetchall()
  conn.close()

  side_chat=[]
  for m in messages:
    side_chat.append({
      "role":m[0],
      "message":m[1]
    })

  return jsonify(side_chat),200

@app.route("/api/delete-session/<session_id>",methods=["DELETE"])
@jwt_required()
def delete_session(session_id):
  user_id = get_jwt_identity()
  conn = get_connect()
  cursor = conn.execute("SELECT id FROM agent WHERE user_id=? AND session_id=?",(user_id,session_id))
  exists = cursor.fetchone()
  if not exists:
    conn.close()
    return jsonify({"error": "Session not found or Unauthorized"}), 404
  conn.execute("DELETE FROM agent WHERE user_id=? AND session_id=?",(user_id,session_id))
  conn.commit()
  conn.close()

  return jsonify({"message": "Chat deleted successfully"}), 200
if __name__ == "__main__":
  app.run(debug=True)