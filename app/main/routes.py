from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.main import bp
from app.models import Employee, SocialMediaAccount, ScrapingJob, AnalysisResult, User, AuditLog, get_setting, set_setting
import json
from app.services.ollama_service import OllamaService
from app import db
from sqlalchemy import func, case, text
from datetime import datetime, timedelta

@bp.route('/')
def index():
    """Home page - redirect to dashboard if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard."""
    # Get statistics
    stats = {
        'total_employees': Employee.query.count(),
        'active_employees': Employee.query.filter_by(status='active').count(),
        'total_social_accounts': SocialMediaAccount.query.count(),
        'recent_analyses': AnalysisResult.query.filter(
            AnalysisResult.created_at >= datetime.utcnow() - timedelta(days=30)
        ).count(),
        'pending_jobs': ScrapingJob.query.filter_by(status='pending').count(),
        'running_jobs': ScrapingJob.query.filter_by(status='running').count()
    }
    
    # Get recent activities
    recent_employees = Employee.query.order_by(Employee.created_at.desc()).limit(5).all()
    recent_analyses = AnalysisResult.query.order_by(AnalysisResult.created_at.desc()).limit(5).all()
    recent_jobs = ScrapingJob.query.order_by(ScrapingJob.started_at.desc()).limit(5).all()
    
    # Get risk distribution
    risk_distribution = db.session.query(
        case(
            (
                AnalysisResult.risk_score < 30, 'Low'
            ),
            (
                AnalysisResult.risk_score < 60, 'Medium'
            ),
            (
                AnalysisResult.risk_score < 80, 'High'
            ),
            else_='Critical'
        ).label('risk_level'),
        func.count(AnalysisResult.id).label('count')
    ).filter(AnalysisResult.risk_score.isnot(None)).group_by('risk_level').all()
    
    return render_template('main/dashboard.html',
                         stats=stats,
                         recent_employees=recent_employees,
                         recent_analyses=recent_analyses,
                         recent_jobs=recent_jobs,
                         risk_distribution=risk_distribution)

@bp.route('/system_status')
@login_required
def system_status():
    """System status page."""
    if not current_user.has_role('system_admin'):
        flash('Access denied. System administrator role required.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Check Ollama service
    try:
        ollama_service = OllamaService()
        ollama_status = ollama_service.test_connection()
    except Exception as e:
        ollama_status = {
            'status': 'error',
            'message': f'Failed to initialize Ollama service: {str(e)}'
        }
    
    # Database status
    try:
        db.session.execute(text('SELECT 1'))
        db_status = {'status': 'success', 'message': 'Database connection OK'}
    except Exception as e:
        db_status = {'status': 'error', 'message': f'Database error: {str(e)}'}
    
    # Get system statistics
    system_stats = {
        'total_users': User.query.count(),
        'active_users': User.query.filter_by(is_active=True).count(),
        'total_audit_logs': AuditLog.query.count(),
        'recent_logins': AuditLog.query.filter(
            AuditLog.action == 'login',
            AuditLog.timestamp >= datetime.utcnow() - timedelta(days=7)
        ).count()
    }
    
    return render_template('main/system_status.html',
                         ollama_status=ollama_status,
                         db_status=db_status,
                         system_stats=system_stats)

@bp.route('/api/dashboard_data')
@login_required
def api_dashboard_data():
    """API endpoint for dashboard data (for AJAX updates)."""
    stats = {
        'pending_jobs': ScrapingJob.query.filter_by(status='pending').count(),
        'running_jobs': ScrapingJob.query.filter_by(status='running').count(),
        'completed_jobs_today': ScrapingJob.query.filter(
            ScrapingJob.status == 'completed',
            ScrapingJob.completed_at >= datetime.utcnow().date()
        ).count()
    }
    
    return jsonify(stats)

@bp.route('/help')
@login_required
def help():
    """Help and documentation page."""
    return render_template('main/help.html')

@bp.route('/about')
@login_required
def about():
    """About page."""
    return render_template('main/about.html')


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Application settings page.

    - Platform managers and system admins can set MAX_POSTS_PER_SCRAPE.
    - Only system admins can set OLLAMA_MODEL and APIFY_API_TOKEN.
    """
    # Permissions
    can_edit_max_posts = current_user.role in ['platform_manager', 'system_admin']
    is_admin = current_user.role == 'system_admin'

    if request.method == 'POST':
        # CSRF protected via global CSRFProtect
        updates = {}

        if can_edit_max_posts:
            max_posts = request.form.get('MAX_POSTS_PER_SCRAPE')
            if max_posts:
                try:
                    val = int(max_posts)
                    if val <= 0:
                        raise ValueError('must be positive')
                    set_setting('MAX_POSTS_PER_SCRAPE', str(val), updated_by=current_user.username)
                    updates['MAX_POSTS_PER_SCRAPE'] = val
                except Exception:
                    flash('MAX_POSTS_PER_SCRAPE must be a positive integer.', 'error')

        if is_admin:
            # Prefer radio-selected model; allow custom override if provided
            selected_model = request.form.get('OLLAMA_MODEL')
            custom_model = request.form.get('OLLAMA_MODEL_CUSTOM')
            final_model = (custom_model or '').strip() or (selected_model or '').strip()
            if final_model:
                set_setting('OLLAMA_MODEL', final_model, updated_by=current_user.username)
                updates['OLLAMA_MODEL'] = final_model

            apify_token = request.form.get('APIFY_API_TOKEN')
            if apify_token is not None and apify_token.strip() != '':
                set_setting('APIFY_API_TOKEN', apify_token.strip(), updated_by=current_user.username)
                updates['APIFY_API_TOKEN'] = '***saved***'

            # Analysis settings (admin only)
            analysis_mode = request.form.get('ANALYSIS_MODE')
            if analysis_mode in ['single', 'staged']:
                set_setting('ANALYSIS_MODE', analysis_mode, updated_by=current_user.username)
                updates['ANALYSIS_MODE'] = analysis_mode

            extra_instructions = request.form.get('PROMPT_EXTRA_INSTRUCTIONS')
            if extra_instructions is not None:
                set_setting('PROMPT_EXTRA_INSTRUCTIONS', extra_instructions, updated_by=current_user.username)
                updates['PROMPT_EXTRA_INSTRUCTIONS'] = 'updated'

            # Per-section prompt overrides
            for key in ['PROMPT_RISK','PROMPT_CHARACTER','PROMPT_BEHAVIOR','PROMPT_REDFLAGS','PROMPT_POSITIVE','PROMPT_ASSESSMENTS']:
                val = request.form.get(key)
                if val is not None:
                    set_setting(key, val, updated_by=current_user.username)
                    updates[key] = 'updated'

            # Provider selection
            provider = request.form.get('ANALYSIS_PROVIDER')
            if provider in ['ollama', 'gemini']:
                set_setting('ANALYSIS_PROVIDER', provider, updated_by=current_user.username)
                updates['ANALYSIS_PROVIDER'] = provider

            # Gemini API key
            gemini_key = request.form.get('GOOGLE_API_KEY')
            if gemini_key is not None and gemini_key.strip() != '':
                set_setting('GOOGLE_API_KEY', gemini_key.strip(), updated_by=current_user.username)
                updates['GOOGLE_API_KEY'] = '***saved***'

        # Assessments (managers and admins can configure)
        if current_user.role in ['platform_manager', 'system_admin']:
            dims = request.form.getlist('ASSESSMENT_DIMENSIONS')
            # Persist as JSON array
            set_setting('ASSESSMENT_DIMENSIONS', json.dumps(dims), updated_by=current_user.username)
            updates['ASSESSMENT_DIMENSIONS'] = dims

        if updates:
            flash('Settings updated successfully.', 'success')
            return redirect(url_for('main.settings'))
        else:
            flash('No changes applied or insufficient permissions.', 'warning')

    # Load current values with fallbacks (display purposes only)
    max_posts_val = get_setting('MAX_POSTS_PER_SCRAPE', None)
    if not max_posts_val:
        max_posts_val = str(int(current_app.config.get('MAX_POSTS_PER_SCRAPE', 1000)))
    current_settings = {
        'MAX_POSTS_PER_SCRAPE': max_posts_val,
        'OLLAMA_MODEL': get_setting('OLLAMA_MODEL', current_app.config.get('OLLAMA_MODEL', 'llama2')),
    }
    # Do not display APIFY token value for security; show placeholder if set
    token_present = bool(get_setting('APIFY_API_TOKEN', None) or current_app.config.get('APIFY_API_TOKEN'))

    # Load available Ollama models for administrator selection
    available_models = []
    if is_admin:
        try:
            available_models = OllamaService().get_available_models() or []
        except Exception:
            available_models = []

    # Load assessment dimensions
    default_dims = [
        'political_orientation',
        'religious_orientation',
        'violence_tendency',
        'political_or_religious_affiliation',
        'suitability_for_sensitive_positions',
        'discrimination_or_bias',
        'personal_issues_shared',
    ]
    try:
        selected_dims = json.loads(get_setting('ASSESSMENT_DIMENSIONS', json.dumps(default_dims)))
    except Exception:
        selected_dims = default_dims

    # Analysis settings current values
    analysis_mode = get_setting('ANALYSIS_MODE', 'single')
    prompt_extra = get_setting('PROMPT_EXTRA_INSTRUCTIONS', '') or ''
    analysis_provider = get_setting('ANALYSIS_PROVIDER', 'ollama') or 'ollama'
    gemini_key_present = bool(get_setting('GOOGLE_API_KEY', None))
    prompt_overrides = {
        'PROMPT_RISK': get_setting('PROMPT_RISK', '') or '',
        'PROMPT_CHARACTER': get_setting('PROMPT_CHARACTER', '') or '',
        'PROMPT_BEHAVIOR': get_setting('PROMPT_BEHAVIOR', '') or '',
        'PROMPT_REDFLAGS': get_setting('PROMPT_REDFLAGS', '') or '',
        'PROMPT_POSITIVE': get_setting('PROMPT_POSITIVE', '') or '',
        'PROMPT_ASSESSMENTS': get_setting('PROMPT_ASSESSMENTS', '') or '',
    }

    return render_template('main/settings.html',
                           current_settings=current_settings,
                           token_present=token_present,
                           can_edit_max_posts=can_edit_max_posts,
                           is_admin=is_admin,
                           available_models=available_models,
                           assessment_dimensions=default_dims,
                           selected_dims=selected_dims,
                           analysis_mode=analysis_mode,
                           prompt_extra=prompt_extra,
                           prompt_overrides=prompt_overrides,
                           analysis_provider=analysis_provider,
                           gemini_key_present=gemini_key_present)

@bp.route('/settings/test_gemini', methods=['POST'])
@login_required
def test_gemini():
    """Test connectivity to Gemini API using stored API key."""
    if current_user.role != 'system_admin':
        flash('Access denied. System admin required.', 'error')
        return redirect(url_for('main.settings'))
    try:
        from app.services.gemini_service import GeminiService
        svc = GeminiService()
        result = svc.test_connection()
        flash(result.get('message', 'Gemini test completed.'), 'success' if result.get('status') == 'success' else 'warning')
    except Exception as e:
        flash(f'Gemini test failed: {str(e)}', 'error')
    return redirect(url_for('main.settings'))
