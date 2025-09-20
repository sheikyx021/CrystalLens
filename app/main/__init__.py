from flask import Blueprint

bp = Blueprint('main', __name__)

# Import routes to register view functions
from app.main import routes  # noqa: E402,F401
