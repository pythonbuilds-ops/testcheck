import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from phoneagent.memory import MemorySystem

def test():
    # Use in-memory SQLite database
    print("Initializing memory system...")
    memory = MemorySystem(":memory:")
    
    print("\nStoring facts...")
    memory.store("wifi_password", "The wifi password for home network is Spring2024!", category="device_info")
    memory.store("mom_phone", "Mom's phone number is 555-0198", category="contact")
    memory.store("uber_loc", "Always get dropped off at the north entrance", category="user_preference")
    memory.store("lock_code", "Screen PIN is 9876", category="device_info")
    print("Facts stored successfully.")
    
    print("\nTesting semantic search (Query has NO exact keyword matches)...")
    query = "what is my login code for the internet?"
    print(f"Query: '{query}'")
    
    results = memory.recall(query, top_k=2)
    print("\nResults:")
    for r in results:
        print(f" -> {r['key']}: {r['value']} (Category: {r['category']})")

if __name__ == "__main__":
    test()
