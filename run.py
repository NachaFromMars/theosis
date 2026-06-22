"""Convenience launcher.

    python run.py            # http://localhost:8000
    THEOSIS_DEMO=1 python run.py   # thử với model giả lập, không cần key
"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("theosis.server:app", host="0.0.0.0", port=port, reload=False)
