import shutil, subprocess

def detect_gpu():
    try: return subprocess.check_output(["nvidia-smi","--query-gpu=name","--format=csv,noheader"],text=True,stderr=subprocess.DEVNULL).strip() or "No NVIDIA GPU"
    except (FileNotFoundError,subprocess.CalledProcessError): return "No NVIDIA GPU"

if __name__ == "__main__":
    print("GPU:",detect_gpu()); print("FFmpeg:",shutil.which("ffmpeg") or "not installed")
