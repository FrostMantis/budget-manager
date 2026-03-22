from flask import Flask
from models import db, Bucket
import routes
from dotenv import load_dotenv
import os

load_dotenv()

def create_app():
    app = Flask(__name__)
    
    # Configuration - Change to MariaDB URI when ready
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DB_URI")
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
    
    db.init_app(app)
    
    # Register the blueprint containing all routes
    app.register_blueprint(routes.bp)
    
    with app.app_context():
        db.create_all()
        # Initialize System Buckets if they don't exist
        if not Bucket.query.filter_by(bucket_type='savings').first():
            db.session.add(Bucket(name="Savings", bucket_type="savings"))
        if not Bucket.query.filter_by(bucket_type='everything').first():
            db.session.add(Bucket(name="Everything", bucket_type="everything"))
        db.session.commit()
        
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0')