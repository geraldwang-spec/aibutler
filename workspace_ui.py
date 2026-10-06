"""Persistent navigation shell; existing views still handle pane requests unchanged."""
from flask import g, render_template, request


PAGE_ENDPOINTS = {
    'dashboard', 'profile', 'records', 'imports', 'import_review',
    'quiz_start', 'quiz_take', 'results', 'analysis', 'body.index',
    'personal_ai.knowledge', 'personal_ai.ai_questions', 'personal_ai.concepts',
    'personal_ai.ai_status', 'personal_ai.wrong_tutor',
    'personal_ai.concept_weakness', 'personal_ai.adaptive_planner',
    'personal_ai.micro_courses', 'personal_ai.micro_course',
    'personal_ai.job_page', 'personal_ai.chat_index', 'personal_ai.chat_page',
}


def register_workspace_ui(app):
    # Authentication, CSRF and read-only guards registered by the base app run first.
    # Sec-Fetch-Dest survives form submissions/redirects inside the same-origin pane.
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True

    @app.context_processor
    def workspace_context():
        return {'workspace_embedded': request.headers.get('Sec-Fetch-Dest') == 'iframe' or request.headers.get('X-Workspace-Fragment') == 'records',
                'workspace_shell': False}

    @app.before_request
    def workspace_shell():
        if (request.method == 'GET' and request.endpoint in PAGE_ENDPOINTS
                and request.headers.get('Sec-Fetch-Dest') != 'iframe'
                and request.headers.get('X-Workspace-Fragment') != 'records'
                and getattr(g, 'user', None)):
            # Do not execute a page's view twice. Its original view executes when
            # the pane loads, including ownership checks and any existing work.
            return render_template('product_base.html', title='我的工作室',
                                   workspace_shell=True,
                                   workspace_url=request.full_path.rstrip('?'))
