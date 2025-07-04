#!/usr/bin/env python3
"""
Launch the Secret AGI web game viewer.

This script starts the FastAPI backend and opens the game viewer in your browser.
"""

import asyncio
import webbrowser
import time
from pathlib import Path
import sys

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """Launch the web viewer."""
    print("🚀 Starting Secret AGI Web Game Viewer...")
    print("=" * 50)
    print()
    print("This will:")
    print("  1. Start the FastAPI backend on http://localhost:8000")
    print("  2. Open the game viewer in your browser")
    print("  3. Allow you to start and monitor games")
    print()
    print("Press Ctrl+C to stop the server")
    print()
    
    try:
        # Import and run the API
        from secret_agi.api.simple_api import app
        import uvicorn
        
        # Start server in a way that allows browser opening
        print("🌐 Starting web server...")
        
        # Open browser after a short delay
        def open_browser():
            time.sleep(2)  # Give server time to start
            print("🔗 Opening browser at http://localhost:8000")
            webbrowser.open("http://localhost:8000")
        
        import threading
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()
        
        # Start the server
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=8000,
            log_level="info"
        )
        
    except ImportError as e:
        print(f"❌ Error: Missing dependencies - {e}")
        print("Make sure you have FastAPI and uvicorn installed:")
        print("  pip install fastapi uvicorn")
        sys.exit(1)
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down web server...")
        
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()