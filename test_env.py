from dotenv import load_dotenv
import os
load_dotenv()
print("Key loaded:", bool(os.environ.get("SARVAM_API_KEY")))
