# test_concurrent_tools.py
from dotenv import load_dotenv
load_dotenv()

from providers import get_provider
import agentic_search

provider, model = get_provider()

conversation = [
    {"role": "user", "content": "Search for the current specs of the iPhone 17 Pro AND the Samsung Galaxy S26 Ultra separately, then tell me the chipset for each."}
]

full_response = ""
for event in agentic_search.run(provider, model, conversation, allowed_tools={"web_search", "web_fetch"}):
    if event["type"] == "text":
        full_response += event["value"]
    elif event["type"] == "activity":
        print(f"[activity] {event['event'].get('label', event['event'].get('kind'))}")

print("\n--- FINAL REPLY ---")
print(full_response)