import os
import json
import sqlite3
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="projectX")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_PATH = "projectx.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_message(conversation_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

class ChatRequest(BaseModel):
    conversation_id: str
    message: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    save_message(req.conversation_id, "user", req.message)

    def event_stream():
        full_response = ""
        stream = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            input=req.message,
            stream=True,
        )
        for event in stream:
            if event.type == "response.output_text.delta":
                full_response += event.delta
                yield f"data: {json.dumps(event.delta)}\n\n"
            elif event.type == "response.completed":
                break
        save_message(req.conversation_id, "assistant", full_response)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")