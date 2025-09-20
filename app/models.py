from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
import json
from functools import lru_cache

class User(UserMixin, db.Model):
    """User model for authentication and role management."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='reviewer')  # platform_manager, system_admin, reviewer
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    audit_logs = db.relationship('AuditLog', backref='user', lazy='dynamic')
    
    def set_password(self, password):
        """Set password hash."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash."""
        return check_password_hash(self.password_hash, password)
    
    def has_role(self, role):
        """Check if user has specific role."""
        return self.role == role
    
    def can_manage_employees(self):
        """Check if user can manage employees."""
        return self.role in ['platform_manager', 'system_admin']
    
    def can_trigger_scraping(self):
        """Check if user can trigger scraping."""
        return self.role in ['platform_manager', 'system_admin']
    
    def can_view_reports(self):
        """Check if user can view reports."""
        return self.role in ['platform_manager', 'system_admin', 'reviewer']
    
    def __repr__(self):
        return f'<User {self.username}>'

class Employee(db.Model):
    """Employee model for storing employee information."""
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    position = db.Column(db.String(100), nullable=True)
    hire_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='active')  # active, inactive, under_review
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    social_accounts = db.relationship('SocialMediaAccount', backref='employee', lazy='dynamic', cascade='all, delete-orphan')
    analysis_results = db.relationship('AnalysisResult', backref='employee', lazy='dynamic', cascade='all, delete-orphan')
    
    @property
    def full_name(self):
        """Get full name."""
        return f"{self.first_name} {self.last_name}"
    
    def get_latest_analysis(self):
        """Get the most recent analysis result."""
        return self.analysis_results.order_by(AnalysisResult.created_at.desc()).first()
    
    def __repr__(self):
        return f'<Employee {self.employee_id}: {self.full_name}>'

class SocialMediaAccount(db.Model):
    """Social media account model."""
    __tablename__ = 'social_media_accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    platform = db.Column(db.String(50), nullable=False)  # twitter, facebook, linkedin, etc.
    username = db.Column(db.String(100), nullable=False)
    profile_url = db.Column(db.String(500), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    last_scraped = db.Column(db.DateTime, nullable=True)
    scrape_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    scraping_jobs = db.relationship('ScrapingJob', backref='social_account', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<SocialAccount {self.platform}: {self.username}>'

class ScrapingJob(db.Model):
    """Scraping job model to track scraping operations."""
    __tablename__ = 'scraping_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    social_account_id = db.Column(db.Integer, db.ForeignKey('social_media_accounts.id'), nullable=False)
    apify_run_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), default='pending')  # pending, running, completed, failed
    posts_scraped = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    scraped_data = db.Column(db.JSON, nullable=True)  # Store scraped posts as JSON
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def get_posts(self):
        """Get scraped posts as list."""
        return self.scraped_data or []
    
    def set_posts(self, posts):
        """Set scraped posts."""
        self.scraped_data = posts
        self.posts_scraped = len(posts) if posts else 0
    
    @property
    def duration(self):
        """Get job duration."""
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return None
    
    def __repr__(self):
        return f'<ScrapingJob {self.id}: {self.status}>'

class AnalysisResult(db.Model):
    """Analysis result model to store AI analysis."""
    __tablename__ = 'analysis_results'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    scraping_job_ids = db.Column(db.JSON, nullable=False)  # List of scraping job IDs used for analysis
    
    # Analysis results
    risk_score = db.Column(db.Float, nullable=True)  # 0-100 risk score
    character_assessment = db.Column(db.Text, nullable=True)
    behavioral_insights = db.Column(db.Text, nullable=True)
    red_flags = db.Column(db.JSON, nullable=True)  # List of identified red flags
    positive_indicators = db.Column(db.JSON, nullable=True)  # List of positive indicators
    
    # Analysis metadata
    posts_analyzed = db.Column(db.Integer, default=0)
    analysis_model = db.Column(db.String(100), nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    analyzed_by = db.Column(db.String(100), nullable=True)  # User who triggered analysis
    
    def get_red_flags(self):
        """Get red flags as list."""
        return self.red_flags or []
    
    def get_positive_indicators(self):
        """Get positive indicators as list."""
        return self.positive_indicators or []
    
    def get_risk_level(self):
        """Get risk level based on score."""
        if self.risk_score is None:
            return 'Unknown'
        elif self.risk_score < 30:
            return 'Low'
        elif self.risk_score < 60:
            return 'Medium'
        elif self.risk_score < 80:
            return 'High'
        else:
            return 'Critical'
    
    def __repr__(self):
        return f'<AnalysisResult {self.id}: Risk {self.risk_score}>'

class AuditLog(db.Model):
    """Audit log model for tracking user actions."""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(50), nullable=True)  # employee, scraping_job, analysis, etc.
    resource_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f'<AuditLog {self.id}: {self.action}>'


class AppSetting(db.Model):
    """Application settings stored as key-value pairs."""
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(80), nullable=True)

    def __repr__(self):
        return f'<AppSetting {self.key}>'


# Settings helper functions
@lru_cache(maxsize=128)
def get_setting(key: str, default=None):
    s = AppSetting.query.filter_by(key=key).first()
    if s is None:
        return default
    return s.value


def set_setting(key: str, value: str, updated_by: str = None):
    s = AppSetting.query.filter_by(key=key).first()
    if s is None:
        s = AppSetting(key=key, value=value, updated_by=updated_by)
        db.session.add(s)
    else:
        s.value = value
        s.updated_by = updated_by
        s.updated_at = datetime.utcnow()
    db.session.commit()
    # Invalidate cache for this key
    try:
        get_setting.cache_clear()
    except Exception:
        pass
    return s
