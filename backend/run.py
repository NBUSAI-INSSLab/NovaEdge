"""开发环境启动入口。

    python run.py                 # 默认 0.0.0.0:5000（已启用 SSE 所需的多线程）
    set PORT=8000 && python run.py
"""

from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
