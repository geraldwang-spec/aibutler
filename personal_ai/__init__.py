from .routes import bp

def register_personal_ai(app):
    app.register_blueprint(bp)
    if not app.config.get('TESTING'):
        from .maintenance import start
        start(app)
        from .jobs import recover
        recover(app)
