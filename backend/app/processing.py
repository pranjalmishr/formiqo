"""Single-instance native processing budget shared by extraction and conversion."""
import asyncio

# Both native families share two slots; they do not each run two 1.5 GiB workers.
native_slots = asyncio.Semaphore(2)
