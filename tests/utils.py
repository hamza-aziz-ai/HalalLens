import asyncio


def run_async(coro):
    return asyncio.run(coro)
