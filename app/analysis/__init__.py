from flask import Blueprint

bp = Blueprint('analysis', __name__)

# Import routes to register view functions
from app.analysis import routes  # noqa: E402,F401
