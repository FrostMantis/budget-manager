from flask import Flask
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from models import db, User, Bucket
import routes
from dotenv import load_dotenv
import os

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DB_URI")
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
    
    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.login_view = 'main.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(routes.bp)
    
    with app.app_context():
        db.create_all()
        
        # Pre-create the two accounts you requested
        users_to_create = [
            ("example", "example"),
            ("placeholder", "placeholder")
        ]
        
        for u_name, u_pass in users_to_create:
            if not User.query.filter_by(username=u_name).first():
                new_user = User(
                    username=u_name, 
                    password_hash=generate_password_hash(u_pass)
                )
                db.session.add(new_user)
                db.session.flush() # Get user ID
                
                # Initialize system buckets for each user
                db.session.add(Bucket(user_id=new_user.id, name="Savings", bucket_type="savings"))
                db.session.add(Bucket(user_id=new_user.id, name="Everything", bucket_type="everything"))
        
        db.session.commit()
        
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0')