from flask import Blueprint

bp = Blueprint('scraping', __name__)

# Import routes to register view functions
from app.scraping import routes  # noqa: E402,F401
