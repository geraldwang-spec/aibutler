document.addEventListener("DOMContentLoaded", () => {
    const body = document.body;
    document.querySelector("[data-sidebar-open]")?.addEventListener("click", () => body.classList.add("sidebar-open"));
    document.querySelectorAll("[data-sidebar-close]").forEach((button) => {
        button.addEventListener("click", () => body.classList.remove("sidebar-open"));
    });

    document.querySelector("[data-password-toggle]")?.addEventListener("click", (event) => {
        const button = event.currentTarget;
        const input = button.parentElement.querySelector("input");
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        button.querySelector("i").className = showing ? "fa fa-eye" : "fa fa-eye-slash";
        button.setAttribute("aria-label", showing ? "顯示密碼" : "隱藏密碼");
    });

    document.querySelectorAll(".task-item input").forEach((checkbox) => {
        checkbox.addEventListener("change", () => checkbox.closest(".task-item").classList.toggle("done", checkbox.checked));
    });
});
