"""Clean old app_package_ entries from memory that use fuzzy keys."""
from phoneagent.memory import MemorySystem

m = MemorySystem()
all_mems = m.get_all_memories(200)
bad = [x for x in all_mems if "app_package" in x["key"]]
for x in bad:
    print(f"  Removing: {x['key']} = {x['value']}")
    m.forget(x["key"])
print(f"Cleaned {len(bad)} old app_package entries")
m.close()
