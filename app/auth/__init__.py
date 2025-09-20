from flask import Blueprint

bp = Blueprint('auth', __name__)

# Import routes to register view functions
from app.auth import routes  # noqa: E402,F401
