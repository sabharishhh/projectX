from mcp_client import MCPClient
c = MCPClient("python", ["mcp_server.py"])
print(c.call_tool("memory_search", {"pattern": "Nolan", "branch": "main"}))