# test_tool_call.py
from dotenv import load_dotenv
load_dotenv()

from providers import get_provider

provider, model = get_provider()

tools = [{
    "type": "function",
    "name": "web_search",
    "description": "Search the web",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}]

messages = [{"role": "user", "content": "search the web for today's date"}]

for event in provider.stream_with_tools(messages, model, tools):
    print(event)