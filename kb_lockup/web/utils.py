"""Utility functions for Streamlit web app"""

import asyncio
import threading


def run_async(coro):
    """Helper to run async code in Streamlit"""
    try:
        # Try to get the current event loop
        asyncio.get_running_loop()
        # If we get here, there's a running loop - use a thread
        
        result = None
        exception = None
        
        def run_in_thread():
            nonlocal result, exception
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                result = new_loop.run_until_complete(coro)
                new_loop.close()
            except Exception as e:
                exception = e
        
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        
        if exception:
            raise exception
        return result
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        return asyncio.run(coro)
