import asyncio
from pocketpaw.tools.builtin.anti_detect_browser import AntiDetectBrowserTool

async def main():
    tool = AntiDetectBrowserTool()
    print(await tool.execute(action="list_profiles"))
    print(await tool.execute(action="list_actors"))

asyncio.run(main())
