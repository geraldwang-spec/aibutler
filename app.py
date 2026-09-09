from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)


@app.route("/")
def index():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # 樣板階段先展示登入動線，之後再接資料庫與帳號驗證。
        return redirect(url_for("dashboard"))
    return render_template("exam_login.html")


@app.route("/dashboard")
def dashboard():
    return render_template("exam.html", page="overview", sections=SECTIONS)


SECTIONS = {
    "overview": ("學習總覽", "home"),
    "sources": ("考試資料庫", "database"),
    "review": ("重點摘要與問答", "book"),
    "mock": ("模擬考試", "pencil-square-o"),
    "results": ("成績與錯題解析", "check-square-o"),
    "analysis": ("考題分析與加強方向", "bar-chart"),
    "wellness": ("讀書與健康提醒", "heart-o"),
}


@app.route("/workspace/<page>")
def workspace(page):
    if page not in SECTIONS:
        from flask import abort
        abort(404)
    return render_template("exam.html", page=page, sections=SECTIONS)


@app.route("/data-visualization")
def data_visualization():
    return redirect(url_for("workspace", page="analysis"))


@app.route("/maps")
def maps():
    return redirect(url_for("workspace", page="mock"))


@app.route("/manage-users")
def manage_users():
    return redirect(url_for("workspace", page="sources"))


@app.route("/preferences")
def preferences():
    return redirect(url_for("workspace", page="wellness"))


@app.route("/logout")
def logout():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=False)
