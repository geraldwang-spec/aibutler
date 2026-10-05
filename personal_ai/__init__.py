from .routes import bp

def register_personal_ai(app):
    app.register_blueprint(bp)
