from flask import Flask
from flask_session import Session
from app.config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY
    Session(app)  # Enable session storage

    from app.routes import main_routes
    app.register_blueprint(main_routes)

    return app
