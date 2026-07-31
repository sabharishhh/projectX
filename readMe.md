cd frontend/
npm run dev

cd backend/
uv run uvicorn main:app --reload

cd memory-engine/
cargo run

docker start searxng
docker update --restart unless-stopped searxng


curl -X POST http://127.0.0.1:8100/reset