import asyncio
import logging
from pocketpaw.config import get_settings
from pocketpaw.agents.open_interpreter import OpenInterpreterAgent

logging.basicConfig(level=logging.INFO)


async def test_oi():
    settings = get_settings()
    # Force OI mode for test
    settings.agent_backend = "open_interpreter"

    agent = OpenInterpreterAgent(settings)

    print("--- Starting OI Test ---")
    async for chunk in agent.run("Calculate 2+2 in python and print the result."):
        print(f"CHUNK: {chunk}")
    print("--- End OI Test ---")


if __name__ == "__main__":
    asyncio.run(test_oi())
