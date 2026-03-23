import os
from flask import Flask
from flask_login import LoginManager
from models import db, User
import routes
from dotenv import load_dotenv
from waitress import serve

load_dotenv()

def create_app():
    app = Flask(__name__)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DB_URI")
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.login_view = 'main.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(routes.bp)
    
    return app

app = create_app()

if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=80)