from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.scraping import bp
from app.models import Employee, SocialMediaAccount, ScrapingJob, AuditLog
from app.services.apify_service import ApifyService
from app import db
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@bp.route('/')
@login_required
def list_jobs():
    """List all scraping jobs."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Filter options
    status_filter = request.args.get('status', '')
    platform_filter = request.args.get('platform', '')
    
    query = ScrapingJob.query.join(SocialMediaAccount)
    
    if status_filter:
        query = query.filter(ScrapingJob.status == status_filter)
    
    if platform_filter:
        query = query.filter(SocialMediaAccount.platform == platform_filter)
    
    jobs = query.order_by(ScrapingJob.started_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('scraping/list.html',
                         jobs=jobs,
                         status_filter=status_filter,
                         platform_filter=platform_filter)

@bp.route('/start/<int:social_account_id>', methods=['POST'])
@login_required
def start_scraping(social_account_id):
    """Start scraping for a social media account."""
    if not current_user.can_trigger_scraping():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('main.dashboard'))
    
    social_account = SocialMediaAccount.query.get_or_404(social_account_id)
    
    # Check if there's already a running job for this account
    existing_job = ScrapingJob.query.filter_by(
        social_account_id=social_account_id,
        status='running'
    ).first()
    
    if existing_job:
        flash('A scraping job is already running for this account.', 'warning')
        return redirect(url_for('employees.view_employee', id=social_account.employee_id))
    
    try:
        # Create scraping job record
        job = ScrapingJob(
            social_account_id=social_account_id,
            status='pending'
        )
        db.session.add(job)
        db.session.flush()  # Get the job ID
        
        # Initialize Apify service
        apify_service = ApifyService()
        
        # Start scraping based on platform
        if social_account.platform == 'twitter':
            result = apify_service.scrape_twitter_profile(social_account.username)
        elif social_account.platform == 'facebook':
            result = apify_service.scrape_facebook_page(social_account.profile_url)
        else:
            raise ValueError(f"Unsupported platform: {social_account.platform}")
        
        # Update job with Apify run ID
        job.apify_run_id = result['run_id']
        job.status = 'running'
        
        # Update social account
        social_account.last_scraped = datetime.utcnow()
        social_account.scrape_count += 1
        
        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='scraping_started',
            resource_type='scraping_job',
            resource_id=job.id,
            details={
                'employee_id': social_account.employee.employee_id,
                'platform': social_account.platform,
                'username': social_account.username,
                'apify_run_id': result['run_id']
            },
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        flash(f'Scraping started for {social_account.platform} account @{social_account.username}', 'success')
        logger.info(f"Started scraping job {job.id} for {social_account.platform} @{social_account.username}")
        
    except Exception as e:
        db.session.rollback()
        error_msg = f"Failed to start scraping: {str(e)}"
        flash(error_msg, 'error')
        logger.error(f"Error starting scraping for account {social_account_id}: {str(e)}")
        
        # Update job status to failed if it was created
        if 'job' in locals():
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.session.commit()
    
    return redirect(url_for('employees.view_employee', id=social_account.employee_id))

@bp.route('/job/<int:job_id>')
@login_required
def view_job(job_id):
    """View scraping job details."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    job = ScrapingJob.query.get_or_404(job_id)
    
    # Get scraped posts
    posts = job.get_posts()
    
    return render_template('scraping/view_job.html', job=job, posts=posts)

@bp.route('/job/<int:job_id>/delete', methods=['POST'])
@login_required
def delete_job(job_id):
    """Delete a scraping job and its stored results."""
    if not current_user.can_trigger_scraping():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('scraping.view_job', job_id=job_id))

    job = ScrapingJob.query.get_or_404(job_id)

    try:
        emp_id = job.social_account.employee.employee_id if job.social_account and job.social_account.employee else None

        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='scraping_job_deleted',
            resource_type='scraping_job',
            resource_id=job.id,
            details={'employee_id': emp_id, 'platform': job.social_account.platform if job.social_account else None},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)

        db.session.delete(job)
        db.session.commit()
        flash('Scraping job deleted successfully.', 'success')
        return redirect(url_for('scraping.list_jobs'))
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete job: {str(e)}', 'error')
        return redirect(url_for('scraping.view_job', job_id=job_id))

@bp.route('/job/<int:job_id>/refresh', methods=['POST'])
@login_required
def refresh_job_status(job_id):
    """Refresh job status from Apify."""
    if not current_user.can_trigger_scraping():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('scraping.view_job', job_id=job_id))
    
    job = ScrapingJob.query.get_or_404(job_id)
    
    if job.status not in ['running', 'pending']:
        flash('Job is not in a refreshable state.', 'warning')
        return redirect(url_for('scraping.view_job', job_id=job_id))
    
    try:
        apify_service = ApifyService()
        status_info = apify_service.get_run_status(job.apify_run_id)
        
        # Update job status
        if status_info['status'] == 'SUCCEEDED':
            # Get results
            results = apify_service.get_run_results(job.apify_run_id)
            processed_posts = apify_service.extract_post_content(
                results, job.social_account.platform
            )
            
            job.status = 'completed'
            job.set_posts(processed_posts)
            job.completed_at = datetime.utcnow()
            
            flash(f'Job completed successfully. Scraped {len(processed_posts)} posts.', 'success')
            
        elif status_info['status'] in ['FAILED', 'ABORTED', 'TIMED-OUT']:
            job.status = 'failed'
            job.error_message = status_info.get('error_message', f"Job {status_info['status'].lower()}")
            job.completed_at = datetime.utcnow()
            
            flash(f'Job failed: {job.error_message}', 'error')
        
        else:
            flash(f'Job status: {status_info["status"]}', 'info')
        
        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='job_status_refreshed',
            resource_type='scraping_job',
            resource_id=job.id,
            details={'new_status': job.status, 'apify_status': status_info['status']},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
    except Exception as e:
        error_msg = f"Failed to refresh job status: {str(e)}"
        flash(error_msg, 'error')
        logger.error(f"Error refreshing job {job_id}: {str(e)}")
    
    return redirect(url_for('scraping.view_job', job_id=job_id))

@bp.route('/api/job/<int:job_id>/status')
@login_required
def api_job_status(job_id):
    """API endpoint to get job status."""
    job = ScrapingJob.query.get_or_404(job_id)
    
    return jsonify({
        'id': job.id,
        'status': job.status,
        'posts_scraped': job.posts_scraped,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'error_message': job.error_message,
        'duration': str(job.duration) if job.duration else None
    })

@bp.route('/bulk_scrape', methods=['GET', 'POST'])
@login_required
def bulk_scrape():
    """Start bulk scraping for multiple accounts."""
    if not current_user.can_trigger_scraping():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        account_ids = request.form.getlist('account_ids')
        
        if not account_ids:
            flash('No accounts selected.', 'error')
            return redirect(url_for('scraping.bulk_scrape'))
        
        started_jobs = 0
        failed_jobs = 0
        
        for account_id in account_ids:
            try:
                social_account = SocialMediaAccount.query.get(account_id)
                if not social_account:
                    continue
                
                # Check if there's already a running job
                existing_job = ScrapingJob.query.filter_by(
                    social_account_id=account_id,
                    status='running'
                ).first()
                
                if existing_job:
                    continue
                
                # Create and start job (similar to start_scraping)
                job = ScrapingJob(
                    social_account_id=account_id,
                    status='pending'
                )
                db.session.add(job)
                db.session.flush()
                
                apify_service = ApifyService()
                
                if social_account.platform == 'twitter':
                    result = apify_service.scrape_twitter_profile(social_account.username)
                elif social_account.platform == 'facebook':
                    result = apify_service.scrape_facebook_page(social_account.profile_url)
                else:
                    continue
                
                job.apify_run_id = result['run_id']
                job.status = 'running'
                social_account.last_scraped = datetime.utcnow()
                social_account.scrape_count += 1
                
                started_jobs += 1
                
            except Exception as e:
                failed_jobs += 1
                logger.error(f"Error starting bulk scraping for account {account_id}: {str(e)}")
        
        # Log bulk action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='bulk_scraping_started',
            details={
                'accounts_selected': len(account_ids),
                'jobs_started': started_jobs,
                'jobs_failed': failed_jobs
            },
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        if started_jobs > 0:
            flash(f'Started {started_jobs} scraping jobs successfully.', 'success')
        if failed_jobs > 0:
            flash(f'{failed_jobs} jobs failed to start.', 'warning')
        
        return redirect(url_for('scraping.list_jobs'))
    
    # GET request - show bulk scrape form
    # Get all active social media accounts
    social_accounts = SocialMediaAccount.query.filter_by(is_active=True).join(Employee).filter_by(status='active').all()
    
    return render_template('scraping/bulk_scrape.html', social_accounts=social_accounts)
