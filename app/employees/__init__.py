from flask import Blueprint

bp = Blueprint('employees', __name__)

# Import routes to register view functions
from app.employees import routes  # noqa: E402,F401
