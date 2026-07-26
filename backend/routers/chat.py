from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from models import ChatRequest
from chat_engine import stream_chat

router = APIRouter()


@router.post("/api/chat")
def chat(req: ChatRequest):
    return StreamingResponse(
        stream_chat(req.conversation_id, req.message),
        media_type="text/event-stream",
    )