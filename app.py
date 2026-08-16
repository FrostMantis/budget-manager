import os
import click
from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from models import db, User
import routes
from dotenv import load_dotenv
from waitress import serve

load_dotenv()

csrf = CSRFProtect()
migrate = Migrate()


def create_app():
    app = Flask(__name__)

    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DB_URI")
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    if not app.config['SECRET_KEY']:
        # CSRF tokens and session cookies are both signed with this. Failing
        # loudly at boot beats silently issuing forgeable sessions.
        raise RuntimeError("SECRET_KEY is not set (check your .env)")

    # Session cookie hardening. SAMESITE='Lax' blunts cross-site CSRF and is
    # safe on plain HTTP, so it is unconditional.
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # SECURE is opt-in, NOT on by default: this app is served over plain HTTP
    # on port 80. Turning it on without TLS makes the browser withhold the
    # session cookie and locks every user out. Set COOKIE_SECURE=true in .env
    # only once the app is actually behind HTTPS.
    app.config['SESSION_COOKIE_SECURE'] = (
        os.getenv("COOKIE_SECURE", "false").lower() == "true"
    )
    if not app.config['SESSION_COOKIE_SECURE']:
        app.logger.warning(
            "SESSION_COOKIE_SECURE is off - session cookies will be sent over "
            "plain HTTP. Put this behind TLS and set COOKIE_SECURE=true."
        )

    db.init_app(app)
    csrf.init_app(app)
    # compare_type lets autogenerate notice Float -> Numeric style changes.
    migrate.init_app(app, db, compare_type=True)

    login_manager = LoginManager()
    login_manager.login_view = 'main.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    app.register_blueprint(routes.bp)
    register_cli(app)

    return app


def register_cli(app):
    """Management commands. There is no self-service registration route, so
    users are created here rather than by hand-writing INSERTs."""

    @app.cli.command("create-user")
    @click.argument("username")
    @click.password_option()
    def create_user(username, password):
        """Create a user and their two system buckets."""
        from werkzeug.security import generate_password_hash
        from models import Bucket

        username = username.strip()
        if not username:
            raise click.ClickException("Username cannot be empty.")
        if User.query.filter_by(username=username).first():
            raise click.ClickException(f"User {username!r} already exists.")

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.flush()

        # Every user needs exactly one 'savings' and one 'everything' bucket;
        # the service layer looks them up with .first() and assumes they exist.
        db.session.add(Bucket(user_id=user.id, name="Savings", bucket_type="savings"))
        db.session.add(Bucket(user_id=user.id, name="Everything", bucket_type="everything"))
        db.session.commit()
        click.echo(f"Created user {username!r} with Savings and Everything buckets.")


app = create_app()

if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=int(os.getenv("PORT", "80")))
