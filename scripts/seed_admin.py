import os
from getpass import getpass

from app import create_app, db
from app.models import User


def main():
    app = create_app()
    with app.app_context():
        username = os.environ.get("ADMIN_USERNAME") or input("Admin username: ")
        email = os.environ.get("ADMIN_EMAIL") or input("Admin email: ")
        role = "system_admin"

        existing = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing:
            print("User already exists:", existing.username)
            return

        password = os.environ.get("ADMIN_PASSWORD") or getpass("Admin password: ")

        user = User(username=username, email=email, role=role, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Admin user created: {username} ({email}) with role {role}")


if __name__ == "__main__":
    main()
