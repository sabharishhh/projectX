import asyncio
import threading
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from models import ChatRequest
from chat_engine import stream_chat

router = APIRouter()

# Strong references to in-flight disconnect-watcher tasks — required so
# asyncio's event loop doesn't garbage-collect them mid-flight. A task
# with no external reference is only weakly held; without this set, the
# watcher could be destroyed moments after creation, before it ever
# detects anything, which is exactly what was happening.
_background_tasks: set[asyncio.Task] = set()

@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    disconnected = threading.Event()
    poll_count = 0

    async def watch_disconnect():
        nonlocal poll_count
        while not disconnected.is_set():
            poll_count += 1
            is_gone = await request.is_disconnected()
            if poll_count % 4 == 0:  # log every ~2s, not every 0.5s — avoid flooding
                print(f"[disconnect-watch] poll #{poll_count}, is_disconnected={is_gone}")
            if is_gone:
                print(f"[disconnect-watch] DETECTED disconnect at poll #{poll_count}")
                disconnected.set()
                return
            await asyncio.sleep(0.5)
        print(f"[disconnect-watch] watcher exiting normally (generator finished first) after {poll_count} polls")

    task = asyncio.create_task(watch_disconnect())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    def generator():
        try:
            yield from stream_chat(req.conversation_id, req.message, disconnected)
        finally:
            disconnected.set()

    return StreamingResponse(generator(), media_type="text/event-stream")