from dotenv import load_dotenv
load_dotenv()

from providers import get_provider

provider, model = get_provider()

# conflicts/forgets awaiting the user's decision (in-process; lost on restart)
PENDING: dict[str, dict] = {}
PENDING_FORGETS: dict[str, dict] = {}