cd frontend/
npm run dev

cd backend/
uv run uvicorn main:app --reload

cd memory-engine/
cargo run

docker start searxng
docker update --restart unless-stopped searxng


curl -X POST http://127.0.0.1:8100/reset

give me a detailed comparison of the current state of the Iran-Israel conflict versus what it looked like a month ago, with sources.

based on what you know about my job, find me the latest news relevant to that industry

who won the most recent F1 race?

is coffee good or bad for your health? cite sources that disagree

explain the difference between a mutex and a semaphore