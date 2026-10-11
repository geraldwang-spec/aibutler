from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
MODELS_DIR = ROOT / "models"

LOCAL_OLLAMA_MODELS = [
    "qwen3.5:4b",  # local classifier + fallback for all cloud roles
    "bge-m3",      # embeddings / RAG / concept similarity
]


def run(cmd, check=True):
    print("> " + " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=check)


def find_ollama():
    exe = shutil.which("ollama")
    if exe:
        return exe
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local.exists():
        return str(local)
    return None


def install_ollama():
    print("[AI Butler] 找不到 Ollama，嘗試使用 winget 安裝。")
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("找不到 winget。請先手動安裝 Ollama for Windows，再重跑 INSTALL_MODELS.bat。")
    run([
        winget,
        "install",
        "--id",
        "Ollama.Ollama",
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ])
    for _ in range(30):
        exe = find_ollama()
        if exe:
            return exe
        time.sleep(1)
    raise RuntimeError("Ollama 已安裝，但目前終端還找不到 ollama.exe。請關閉視窗重開後再執行。")


def ensure_ollama_running(ollama):
    # On Windows the desktop app usually starts the server. If it is not running,
    # start `ollama serve` detached enough for this installer to continue.
    try:
        subprocess.run([ollama, "list"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=True)
        return
    except Exception:
        print("[AI Butler] Ollama server 尚未啟動，嘗試啟動 ollama serve...")
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        for _ in range(25):
            time.sleep(1)
            try:
                subprocess.run([ollama, "list"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)
                return
            except Exception:
                pass
        raise RuntimeError("無法啟動 Ollama server。請先手動開啟 Ollama 再重試。")


def ensure_env():
    if ENV_PATH.exists():
        return
    ENV_PATH.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")


def update_env(updates):
    ensure_env()
    raw = ENV_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()
    seen = set()
    out = []
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def configure_hybrid():
    # Do NOT overwrite GROQ_API_KEY if the user already entered one.
    update_env({
        "LLM_PROVIDER": "ollama",
        "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "LLM_MODEL": "qwen3.5:4b",
        "CLASSIFIER_PROVIDER": "ollama",
        "CLASSIFIER_BASE_URL": "http://127.0.0.1:11434/v1",
        "CLASSIFIER_MODEL": "qwen3.5:4b",
        "PARSER_PROVIDER": "ollama",
        "PARSER_BASE_URL": "http://127.0.0.1:11434/v1",
        "PARSER_MODEL": "qwen3.5:4b",
        "GENERATOR_PROVIDER": "groq",
        "GENERATOR_BASE_URL": "https://api.groq.com/openai/v1",
        "GENERATOR_MODEL": "qwen/qwen3.8-27b",
        "GENERATOR_FALLBACK_PROVIDER": "ollama",
        "GENERATOR_FALLBACK_BASE_URL": "http://127.0.0.1:11434/v1",
        "GENERATOR_FALLBACK_MODEL": "qwen3.5:4b",
        "REVIEWER_PROVIDER": "groq",
        "REVIEWER_BASE_URL": "https://api.groq.com/openai/v1",
        "REVIEWER_MODEL": "qwen/qwen3.8-27b",
        "REVIEWER_FALLBACK_PROVIDER": "ollama",
        "REVIEWER_FALLBACK_BASE_URL": "http://127.0.0.1:11434/v1",
        "REVIEWER_FALLBACK_MODEL": "qwen3.5:4b",
        "COURSE_PROVIDER": "groq",
        "COURSE_BASE_URL": "https://api.groq.com/openai/v1",
        "COURSE_MODEL": "openai/gpt-oss-120b",
        "COURSE_FALLBACK_PROVIDER": "ollama",
        "COURSE_FALLBACK_BASE_URL": "http://127.0.0.1:11434/v1",
        "COURSE_FALLBACK_MODEL": "qwen3.5:4b",
        "TUTOR_PROVIDER": "groq",
        "TUTOR_BASE_URL": "https://api.groq.com/openai/v1",
        "TUTOR_MODEL": "openai/gpt-oss-120b",
        "TUTOR_FALLBACK_PROVIDER": "ollama",
        "TUTOR_FALLBACK_BASE_URL": "http://127.0.0.1:11434/v1",
        "TUTOR_FALLBACK_MODEL": "qwen3.5:4b",
        "EMBEDDING_PROVIDER": "ollama",
        "EMBEDDING_BASE_URL": "http://127.0.0.1:11434",
        "EMBEDDING_MODEL": "bge-m3",
        "STT_PROVIDER": "faster_whisper",
        "STT_MODEL": "large-v3",
        "TTS_PROVIDER": "kokoro",
        "TTS_MODEL": "hexgrad/Kokoro-82M-v1.1-zh",
        "TTS_LANGUAGE": "z",
        "VOICE_ENABLED": "false",
    })


def install_voice_packages_and_weights():
    print("\n[AI Butler] 安裝語音模型依賴（Whisper / Kokoro）...")
    # Voice is optional at runtime, but the installer prepares it now for home validation.
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "huggingface_hub>=0.24",
        "faster-whisper>=1.1,<2",
        "kokoro>=0.9.4,<1",
        "misaki[zh]>=0.9.4",
        "soundfile>=0.12",
    ])

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    script = r'''
from pathlib import Path
from huggingface_hub import snapshot_download
root = Path(r"%s")
root.mkdir(parents=True, exist_ok=True)
print("[AI Butler] Download faster-whisper large-v3...")
snapshot_download(repo_id="Systran/faster-whisper-large-v3", local_dir=str(root / "faster-whisper-large-v3"))
print("[AI Butler] Download Kokoro Mandarin v1.1...")
snapshot_download(repo_id="hexgrad/Kokoro-82M-v1.1-zh", local_dir=str(root / "Kokoro-82M-v1.1-zh"))
print("[AI Butler] Voice model weights downloaded.")
''' % str(MODELS_DIR).replace("\\", "\\\\")
    run([sys.executable, "-c", script])


def main():
    parser = argparse.ArgumentParser(description="Prepare real AI models for AI Butler.")
    parser.add_argument("--legacy-local", action="store_true", help="明確啟用舊版 Ollama／語音下載與設定覆寫")
    parser.add_argument("--skip-voice", action="store_true", help="只下載 Ollama 模型，不下載 Whisper/Kokoro")
    args = parser.parse_args()

    if not args.legacy_local:
        run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'tools' / 'setup_exam_ai.ps1'), '-Python', sys.executable])
        print('CPU 模組已安裝。Groq 設定與金鑰保留；不下載或啟動本地 LLM。')
        return

    print("=" * 66)
    print("AI Butler - REAL MODEL INSTALLER")
    print("Local: qwen3.5:4b + bge-m3")
    print("Cloud roles: Groq qwen3.8-27b / gpt-oss-120b (no download needed)")
    print("Voice: Whisper large-v3 + Kokoro Mandarin v1.1")
    print("=" * 66)

    ollama = find_ollama() or install_ollama()
    ensure_ollama_running(ollama)

    for model in LOCAL_OLLAMA_MODELS:
        print(f"\n[AI Butler] Pull Ollama model: {model}")
        run([ollama, "pull", model])

    print("\n[AI Butler] Installed Ollama models:")
    run([ollama, "list"], check=False)

    configure_hybrid()
    print(f"\n[AI Butler] Hybrid real-model profile written to {ENV_PATH}")
    print("[AI Butler] If GROQ_API_KEY is blank, Generator/Reviewer/Course/Tutor will fall back to local qwen3.5:4b.")

    if not args.skip_voice:
        try:
            install_voice_packages_and_weights()
        except Exception as exc:
            # Core learning flow should remain usable even if Windows/Python voice deps fail.
            print(f"\n[WARNING] Voice model setup failed: {exc}")
            print("Core LLM/RAG models are already installed. You can retry voice setup later.")

    print("\nDONE")
    print("1) Optional: put your Groq key into .env -> GROQ_API_KEY=...")
    print("2) Run: python app.py")
    print("3) Open AI 模型與環境 and test Classifier / Generator / Reviewer / Embedding")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        raise SystemExit(1)
