"""Start Lead Finder on this computer and open it in the browser."""
import os
import threading
import webbrowser

import uvicorn

PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    uvicorn.run("server:app", host=os.environ.get("HOST", "127.0.0.1"), port=PORT)
