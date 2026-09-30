from pathlib import Path

def cleanup(paths):
    for item in paths:
        try:
            p=Path(item)
            if p.is_file(): p.unlink()
        except OSError: pass
