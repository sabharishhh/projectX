# test_mcp_basic.py
from mcp_client import MCPClient

c = MCPClient("python", ["mcp_server.py"])
print(c.list_tools())
print(c.call_tool("web_search", {"query": "test query"}))
c.close()