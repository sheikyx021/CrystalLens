from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.employees import bp
from app.models import Employee, SocialMediaAccount, AnalysisResult, AuditLog
from app import db
from datetime import datetime

@bp.route('/')
@login_required
def list_employees():
    """List all employees."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Search functionality
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    department_filter = request.args.get('department', '')
    
    query = Employee.query
    
    if search:
        query = query.filter(
            db.or_(
                Employee.first_name.contains(search),
                Employee.last_name.contains(search),
                Employee.employee_id.contains(search),
                Employee.email.contains(search)
            )
        )
    
    if status_filter:
        query = query.filter(Employee.status == status_filter)
    
    if department_filter:
        query = query.filter(Employee.department == department_filter)
    
    employees = query.order_by(Employee.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Get filter options
    departments = db.session.query(Employee.department.distinct()).filter(
        Employee.department.isnot(None)
    ).all()
    departments = [d[0] for d in departments if d[0]]
    
    return render_template('employees/list.html',
                         employees=employees,
                         search=search,
                         status_filter=status_filter,
                         department_filter=department_filter,
                         departments=departments)

@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_employee():
    """Create new employee."""
    if not current_user.can_manage_employees():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('employees.list_employees'))
    
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        department = request.form.get('department')
        position = request.form.get('position')
        hire_date = request.form.get('hire_date')
        notes = request.form.get('notes')
        
        # Validation
        if not all([employee_id, first_name, last_name]):
            flash('Employee ID, first name, and last name are required.', 'error')
            return render_template('employees/create.html')
        
        # Check if employee ID already exists
        if Employee.query.filter_by(employee_id=employee_id).first():
            flash('Employee ID already exists.', 'error')
            return render_template('employees/create.html')
        
        # Parse hire date
        hire_date_obj = None
        if hire_date:
            try:
                hire_date_obj = datetime.strptime(hire_date, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid hire date format.', 'error')
                return render_template('employees/create.html')
        
        # Create employee
        employee = Employee(
            employee_id=employee_id,
            first_name=first_name,
            last_name=last_name,
            email=email if email else None,
            department=department if department else None,
            position=position if position else None,
            hire_date=hire_date_obj,
            notes=notes if notes else None
        )
        
        db.session.add(employee)
        
        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='employee_created',
            resource_type='employee',
            details={'employee_id': employee_id, 'name': f"{first_name} {last_name}"},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        flash(f'Employee {employee.full_name} created successfully.', 'success')
        return redirect(url_for('employees.view_employee', id=employee.id))
    
    return render_template('employees/create.html')

@bp.route('/<int:id>')
@login_required
def view_employee(id):
    """View employee details."""
    if not current_user.can_view_reports():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    employee = Employee.query.get_or_404(id)
    
    # Get social media accounts
    social_accounts = employee.social_accounts.all()
    
    # Get latest analysis
    latest_analysis = employee.get_latest_analysis()
    
    # Get analysis history
    analysis_history = employee.analysis_results.order_by(AnalysisResult.created_at.desc()).limit(10).all()
    
    return render_template('employees/view.html',
                         employee=employee,
                         social_accounts=social_accounts,
                         latest_analysis=latest_analysis,
                         analysis_history=analysis_history)

@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_employee(id):
    """Edit employee."""
    if not current_user.can_manage_employees():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('employees.view_employee', id=id))
    
    employee = Employee.query.get_or_404(id)
    
    if request.method == 'POST':
        employee.first_name = request.form.get('first_name')
        employee.last_name = request.form.get('last_name')
        employee.email = request.form.get('email') if request.form.get('email') else None
        employee.department = request.form.get('department') if request.form.get('department') else None
        employee.position = request.form.get('position') if request.form.get('position') else None
        employee.status = request.form.get('status')
        employee.notes = request.form.get('notes') if request.form.get('notes') else None
        
        # Parse hire date
        hire_date = request.form.get('hire_date')
        if hire_date:
            try:
                employee.hire_date = datetime.strptime(hire_date, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid hire date format.', 'error')
                return render_template('employees/edit.html', employee=employee)
        else:
            employee.hire_date = None
        
        employee.updated_at = datetime.utcnow()
        
        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='employee_updated',
            resource_type='employee',
            resource_id=employee.id,
            details={'employee_id': employee.employee_id, 'name': employee.full_name},
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        flash(f'Employee {employee.full_name} updated successfully.', 'success')
        return redirect(url_for('employees.view_employee', id=employee.id))
    
    return render_template('employees/edit.html', employee=employee)

@bp.route('/<int:id>/add_social_account', methods=['GET', 'POST'])
@login_required
def add_social_account(id):
    """Add social media account to employee."""
    if not current_user.can_manage_employees():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('employees.view_employee', id=id))
    
    employee = Employee.query.get_or_404(id)
    
    if request.method == 'POST':
        platform = request.form.get('platform')
        username = request.form.get('username')
        profile_url = request.form.get('profile_url')
        
        if not all([platform, username, profile_url]):
            flash('All fields are required.', 'error')
            return render_template('employees/add_social_account.html', employee=employee)
        
        # Check if account already exists
        existing = SocialMediaAccount.query.filter_by(
            employee_id=employee.id,
            platform=platform,
            username=username
        ).first()
        
        if existing:
            flash('This social media account already exists for this employee.', 'error')
            return render_template('employees/add_social_account.html', employee=employee)
        
        # Create social media account
        social_account = SocialMediaAccount(
            employee_id=employee.id,
            platform=platform,
            username=username,
            profile_url=profile_url
        )
        
        db.session.add(social_account)
        
        # Log the action
        audit_log = AuditLog(
            user_id=current_user.id,
            action='social_account_added',
            resource_type='social_account',
            details={
                'employee_id': employee.employee_id,
                'platform': platform,
                'username': username
            },
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        flash(f'{platform.title()} account added successfully.', 'success')
        return redirect(url_for('employees.view_employee', id=employee.id))
    
    return render_template('employees/add_social_account.html', employee=employee)

@bp.route('/social_account/<int:id>/delete', methods=['POST'])
@login_required
def delete_social_account(id):
    """Delete social media account."""
    if not current_user.can_manage_employees():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('main.dashboard'))
    
    social_account = SocialMediaAccount.query.get_or_404(id)
    employee_id = social_account.employee_id
    
    # Log the action
    audit_log = AuditLog(
        user_id=current_user.id,
        action='social_account_deleted',
        resource_type='social_account',
        resource_id=social_account.id,
        details={
            'employee_id': social_account.employee.employee_id,
            'platform': social_account.platform,
            'username': social_account.username
        },
        ip_address=request.remote_addr
    )
    db.session.add(audit_log)
    
    db.session.delete(social_account)
    db.session.commit()
    
    flash('Social media account deleted successfully.', 'success')
    return redirect(url_for('employees.view_employee', id=employee_id))

@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_employee(id):
    """Delete employee."""
    if not current_user.can_manage_employees():
        flash('Access denied. Platform manager role required.', 'error')
        return redirect(url_for('employees.view_employee', id=id))
    
    employee = Employee.query.get_or_404(id)
    employee_name = employee.full_name
    employee_id_str = employee.employee_id
    
    # Log the action
    audit_log = AuditLog(
        user_id=current_user.id,
        action='employee_deleted',
        resource_type='employee',
        resource_id=employee.id,
        details={'employee_id': employee_id_str, 'name': employee_name},
        ip_address=request.remote_addr
    )
    db.session.add(audit_log)
    
    db.session.delete(employee)
    db.session.commit()
    
    flash(f'Employee {employee_name} deleted successfully.', 'success')
    return redirect(url_for('employees.list_employees'))
