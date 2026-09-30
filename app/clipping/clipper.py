from pathlib import Path
import subprocess

def clip_video(source: str, clips: list[tuple[str,str]], output_dir="clips") -> list[str]:
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True); results=[]
    for i,(start,end) in enumerate(clips,1):
        target=out/f"clip_{i:02d}.mp4"
        subprocess.run(["ffmpeg","-y","-ss",start,"-to",end,"-i",source,"-c","copy",str(target)],check=True)
        results.append(str(target))
    return results
