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
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    return render_template("index.html")


@app.route("/data-visualization")
def data_visualization():
    return render_template("data-visualization.html")


@app.route("/maps")
def maps():
    return render_template("maps.html")


@app.route("/manage-users")
def manage_users():
    return render_template("manage-users.html")


@app.route("/preferences")
def preferences():
    return render_template("preferences.html")


@app.route("/logout")
def logout():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=False)
