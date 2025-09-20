from flask import render_template, redirect, url_for, flash, request, jsonify, make_response
from flask_login import login_required, current_user
from app.analysis import bp
from app.models import Employee, AnalysisResult, ScrapingJob, AuditLog, SocialMediaAccount
from app.services.ollama_service import OllamaService
from app.services.gemini_service import GeminiService
from app.models import get_setting
from app import db
from datetime import datetime
import logging
import csv
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from sqlalchemy import func, case

logger = logging.getLogger(__name__)

@bp.route('/')
@login_required
def list_analyses():
    """List all analysis results."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Filter options
    risk_filter = request.args.get('risk_level', '')
    department_filter = request.args.get('department', '')
    
    query = AnalysisResult.query.join(Employee)
    
    if risk_filter:
        if risk_filter == 'low':
            query = query.filter(AnalysisResult.risk_score < 30)
        elif risk_filter == 'medium':
            query = query.filter(AnalysisResult.risk_score.between(30, 59))
        elif risk_filter == 'high':
            query = query.filter(AnalysisResult.risk_score.between(60, 79))
        elif risk_filter == 'critical':
            query = query.filter(AnalysisResult.risk_score >= 80)
    
    if department_filter:
        query = query.filter(Employee.department == department_filter)
    
    analyses = query.order_by(AnalysisResult.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Get filter options
    departments = db.session.query(Employee.department.distinct()).filter(
        Employee.department.isnot(None)
    ).all()
    departments = [d[0] for d in departments if d[0]]
    
    return render_template('analysis/list.html',
                         analyses=analyses,
                         risk_filter=risk_filter,
                         department_filter=department_filter,
                         departments=departments)

@bp.route('/<int:id>')
@login_required
def view_analysis(id):
    """View detailed analysis result."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    analysis = AnalysisResult.query.get_or_404(id)
    
    # Get the scraping jobs used for this analysis
    scraping_jobs = ScrapingJob.query.filter(
        ScrapingJob.id.in_(analysis.scraping_job_ids)
    ).all()

    # Build post reference map in the same order jobs were saved
    post_refs = []
    try:
        idx = 1
        for job_id in analysis.scraping_job_ids:
            job = next((j for j in scraping_jobs if j.id == job_id), None)
            if not job:
                continue
            posts = job.get_posts() or []
            for p in posts:
                url = p.get('url') or p.get('permalink') or p.get('link')
                if not url:
                    # Fallback to internal job page if external URL is unavailable
                    url = f"/scraping/job/{job.id}"
                post_refs.append({
                    'index': idx,
                    'url': url,
                    'created_at': p.get('created_at')
                })
                idx += 1
    except Exception:
        post_refs = []
    
    return render_template('analysis/view.html', 
                         analysis=analysis, 
                         scraping_jobs=scraping_jobs,
                         post_refs=post_refs)

@bp.route('/start/<int:employee_id>', methods=['POST'])
@login_required
def start_analysis(employee_id):
    """Start AI analysis for an employee."""
    if not current_user.can_trigger_scraping():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('employees.view_employee', id=employee_id))
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Get completed scraping jobs for this employee (explicit join to avoid ambiguity)
    completed_jobs = (
        ScrapingJob.query
        .join(SocialMediaAccount, ScrapingJob.social_account_id == SocialMediaAccount.id)
        .filter(
            ScrapingJob.status == 'completed',
            SocialMediaAccount.employee_id == employee.id
        )
        .all()
    )
    
    if not completed_jobs:
        flash('No completed scraping jobs found for this employee.', 'error')
        return redirect(url_for('employees.view_employee', id=employee_id))
    
    try:
        # Collect all posts from completed jobs
        all_posts = []
        job_ids = []
        
        for job in completed_jobs:
            posts = job.get_posts()
            all_posts.extend(posts)
            job_ids.append(job.id)
        
        if not all_posts:
            flash('No posts found in completed scraping jobs.', 'error')
            return redirect(url_for('employees.view_employee', id=employee_id))
        
        # Prepare employee information for analysis
        employee_info = {
            'employee_id': employee.employee_id,
            'full_name': employee.full_name,
            'department': employee.department,
            'position': employee.position
        }
        
        # Initialize analysis provider based on settings
        provider = (get_setting('ANALYSIS_PROVIDER', 'ollama') or 'ollama').lower()
        if provider == 'gemini':
            service = GeminiService()
        else:
            service = OllamaService()
        
        # For Ollama, ensure availability; Gemini is external HTTP API
        if isinstance(service, OllamaService) and not service.is_available():
            flash('AI analysis service is not available. Please check Ollama configuration.', 'error')
            return redirect(url_for('employees.view_employee', id=employee_id))
        
        logger.info(f"Starting analysis for employee {employee.employee_id} with {len(all_posts)} posts")
        
        # Run the analysis with selected checks (if any)
        selected_checks = request.form.getlist('CHECKS')  # values like: risk, character, behavior, redflags, positive, assessments
        analysis_result = service.analyze_social_media_posts(all_posts, employee_info, selected_checks=selected_checks)

        # Normalize defaults
        analysis_result['red_flags'] = analysis_result.get('red_flags') or []
        analysis_result['positive_indicators'] = analysis_result.get('positive_indicators') or []

        # Risk fallback if missing
        if analysis_result.get('risk_score') in (None, ''):
            # Simple heuristic: each red flag +15, cap at 95; if none, 20
            rf_count = len(analysis_result['red_flags'])
            fallback_risk = 20 if rf_count == 0 else min(95, rf_count * 15)
            analysis_result['risk_score'] = float(fallback_risk)

        # Prune non-selected sections from persistence (keep only what user chose)
        wanted = set(selected_checks or ['risk','character','behavior','redflags','positive','assessments'])
        if 'character' not in wanted:
            analysis_result['character_assessment'] = ''
        # Preserve behavioral_insights if assessments were included (assessments are appended there)
        if 'behavior' not in wanted and 'assessments' not in wanted:
            analysis_result['behavioral_insights'] = ''
        if 'redflags' not in wanted:
            analysis_result['red_flags'] = []
        if 'positive' not in wanted:
            analysis_result['positive_indicators'] = []
        
        # Create analysis record
        analysis = AnalysisResult(
            employee_id=employee_id,
            scraping_job_ids=job_ids,
            risk_score=analysis_result.get('risk_score'),
            character_assessment=analysis_result.get('character_assessment'),
            behavioral_insights=analysis_result.get('behavioral_insights'),
            red_flags=analysis_result.get('red_flags'),
            positive_indicators=analysis_result.get('positive_indicators'),
            posts_analyzed=analysis_result.get('posts_analyzed', len(all_posts)),
            analysis_model=analysis_result.get('analysis_model'),
            confidence_score=analysis_result.get('confidence_score'),
            analyzed_by=current_user.username
        )
        
        db.session.add(analysis)
        
        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='analysis_started',
            resource_type='analysis_result',
            details={
                'employee_id': employee.employee_id,
                'posts_analyzed': len(all_posts),
                'scraping_jobs': job_ids,
                'risk_score': analysis_result.get('risk_score')
            },
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        flash(f'AI analysis completed for {employee.full_name}. Risk score: {analysis.risk_score or "N/A"}', 'success')
        logger.info(f"Analysis completed for employee {employee.employee_id}, analysis ID: {analysis.id}")
        
        return redirect(url_for('analysis.view_analysis', id=analysis.id))
        
    except Exception as e:
        db.session.rollback()
        error_msg = f"Analysis failed: {str(e)}"
        flash(error_msg, 'error')
        logger.error(f"Error during analysis for employee {employee_id}: {str(e)}")
        
        return redirect(url_for('employees.view_employee', id=employee_id))

@bp.route('/export/<int:id>/pdf')
@login_required
def export_pdf(id):
    """Export analysis result as PDF."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    analysis = AnalysisResult.query.get_or_404(id)
    
    # Create PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        textColor=colors.darkblue
    )
    story.append(Paragraph("Social Media Analysis Report", title_style))
    story.append(Spacer(1, 12))
    
    # Employee Information
    story.append(Paragraph("Employee Information", styles['Heading2']))
    employee_data = [
        ['Employee ID:', analysis.employee.employee_id],
        ['Name:', analysis.employee.full_name],
        ['Department:', analysis.employee.department or 'N/A'],
        ['Position:', analysis.employee.position or 'N/A'],
        ['Analysis Date:', analysis.created_at.strftime('%Y-%m-%d %H:%M:%S')],
        ['Analyzed By:', analysis.analyzed_by or 'System']
    ]
    
    employee_table = Table(employee_data, colWidths=[2*72, 4*72])
    employee_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(employee_table)
    story.append(Spacer(1, 20))
    
    # Risk Assessment
    story.append(Paragraph("Risk Assessment", styles['Heading2']))
    risk_score = analysis.risk_score or 0
    risk_level = analysis.get_risk_level()
    
    risk_color = colors.green
    if risk_score >= 60:
        risk_color = colors.red
    elif risk_score >= 30:
        risk_color = colors.orange
    
    risk_style = ParagraphStyle(
        'RiskStyle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=risk_color,
        spaceAfter=12
    )
    
    story.append(Paragraph(f"Risk Score: {risk_score}/100 ({risk_level})", risk_style))
    story.append(Paragraph(f"Confidence: {analysis.confidence_score or 0}/100", styles['Normal']))
    story.append(Paragraph(f"Posts Analyzed: {analysis.posts_analyzed}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Character Assessment
    if analysis.character_assessment:
        story.append(Paragraph("Character Assessment", styles['Heading2']))
        story.append(Paragraph(analysis.character_assessment, styles['Normal']))
        story.append(Spacer(1, 20))
    
    # Behavioral Insights
    if analysis.behavioral_insights:
        story.append(Paragraph("Behavioral Insights", styles['Heading2']))
        story.append(Paragraph(analysis.behavioral_insights, styles['Normal']))
        story.append(Spacer(1, 20))
    
    # Red Flags
    red_flags = analysis.get_red_flags()
    if red_flags:
        story.append(Paragraph("Red Flags", styles['Heading2']))
        for flag in red_flags:
            story.append(Paragraph(f"• {flag}", styles['Normal']))
        story.append(Spacer(1, 20))
    
    # Positive Indicators
    positive_indicators = analysis.get_positive_indicators()
    if positive_indicators:
        story.append(Paragraph("Positive Indicators", styles['Heading2']))
        for indicator in positive_indicators:
            story.append(Paragraph(f"• {indicator}", styles['Normal']))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    # Log export action
    audit_log = AuditLog(
        user_id=current_user.id,
        action='analysis_exported_pdf',
        resource_type='analysis_result',
        resource_id=analysis.id,
        details={'employee_id': analysis.employee.employee_id},
        ip_address=request.remote_addr
    )
    db.session.add(audit_log)
    db.session.commit()
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=analysis_{analysis.employee.employee_id}_{analysis.id}.pdf'
    
    return response

@bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_analysis(id):
    """Delete a specific analysis result."""
    # Only system_admin or platform_manager can delete analyses
    if getattr(current_user, 'role', None) not in ['system_admin', 'platform_manager']:
        flash('Access denied. Insufficient permissions to delete analyses.', 'error')
        return redirect(url_for('analysis.view_analysis', id=id))

    analysis = AnalysisResult.query.get_or_404(id)

    try:
        emp_id = analysis.employee.employee_id if analysis.employee else None

        db.session.delete(analysis)

        # Audit log
        audit_log = AuditLog(
            user_id=current_user.id,
            action='analysis_deleted',
            resource_type='analysis_result',
            resource_id=id,
            details={'employee_id': emp_id},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        db.session.commit()

        flash('Analysis deleted successfully.', 'success')
        return redirect(url_for('analysis.list_analyses'))
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete analysis: {str(e)}', 'error')
        return redirect(url_for('analysis.view_analysis', id=id))

@bp.route('/export/csv')
@login_required
def export_csv():
    """Export all analysis results as CSV."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Get all analyses
    analyses = AnalysisResult.query.join(Employee).all()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Employee ID', 'Employee Name', 'Department', 'Position',
        'Analysis Date', 'Risk Score', 'Risk Level', 'Confidence Score',
        'Posts Analyzed', 'Red Flags Count', 'Positive Indicators Count',
        'Analyzed By'
    ])
    
    # Write data
    for analysis in analyses:
        writer.writerow([
            analysis.employee.employee_id,
            analysis.employee.full_name,
            analysis.employee.department or '',
            analysis.employee.position or '',
            analysis.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            analysis.risk_score or '',
            analysis.get_risk_level(),
            analysis.confidence_score or '',
            analysis.posts_analyzed,
            len(analysis.get_red_flags()),
            len(analysis.get_positive_indicators()),
            analysis.analyzed_by or ''
        ])
    
    # Log export action
    audit_log = AuditLog(
        user_id=current_user.id,
        action='analyses_exported_csv',
        details={'total_analyses': len(analyses)},
        ip_address=request.remote_addr
    )
    db.session.add(audit_log)
    db.session.commit()
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=social_media_analyses_{datetime.now().strftime("%Y%m%d")}.csv'
    
    return response

@bp.route('/dashboard')
@login_required
def analysis_dashboard():
    """Analysis dashboard with charts and statistics."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Get analysis statistics
    total_analyses = AnalysisResult.query.count()
    
    # Risk distribution
    risk_stats = db.session.query(
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
    
    # Department risk analysis
    dept_risk = db.session.query(
        Employee.department,
        db.func.avg(AnalysisResult.risk_score).label('avg_risk'),
        db.func.count(AnalysisResult.id).label('count')
    ).join(AnalysisResult).filter(
        Employee.department.isnot(None),
        AnalysisResult.risk_score.isnot(None)
    ).group_by(Employee.department).all()
    
    # Recent high-risk analyses
    high_risk_analyses = AnalysisResult.query.filter(
        AnalysisResult.risk_score >= 60
    ).order_by(AnalysisResult.created_at.desc()).limit(10).all()
    
    return render_template('analysis/dashboard.html',
                         total_analyses=total_analyses,
                         risk_stats=risk_stats,
                         dept_risk=dept_risk,
                         high_risk_analyses=high_risk_analyses)
