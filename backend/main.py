import ledger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import db
import extraction
from state import provider, model  # noqa: F401 — importing triggers get_provider() once, correctly ordered after load_dotenv() inside state.py
from routers import chat, conversations, memory, merge

app = FastAPI(title="projectX")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()
ledger.init_ledger()
extraction.start()

try:
    httpx.post(f"{MEMORY_URL}/retrieve", json={"query": "warmup", "max_units": 1}, timeout=30.0)
except Exception:
    pass

app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(memory.router)
app.include_router(merge.router)


@app.on_event("shutdown")
def _shutdown():
    extraction.close()


@app.get("/health")
def health():
    return {"status": "ok"}