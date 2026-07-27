from fastapi import APIRouter

import db
import ledger

router = APIRouter()


@router.get("/api/messages/{conversation_id}")
def get_messages(conversation_id: str):
    return db.load_messages(conversation_id)


@router.delete("/api/messages/{conversation_id}")
def clear_messages(conversation_id: str):
    db.clear_messages(conversation_id)
    ledger.log("conversation_cleared", "chat history wiped", conversation_id, actor="user")
    return {"cleared": conversation_id}


@router.get("/api/conversations")
def list_conversations():
    return db.list_conversations()


@router.get("/api/ledger")
def get_ledger(limit: int = 50):
    return ledger.recent(limit)

@router.get("/api/retrieval-trace/{conversation_id}")
def get_retrieval_trace(conversation_id: str, limit: int = 20):
    return db.get_retrieval_traces(conversation_id, limit)