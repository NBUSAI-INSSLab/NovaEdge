"""Flask 扩展单例。"""

from __future__ import annotations

from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
cors = CORS()
jwt = JWTManager()
