"""DMS Analytics — Entry point"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.main import main

if __name__ == "__main__":
    main()
