import os, math
from pathlib import Path
from pyrogram import Client

TELEGRAM_LIMIT=2_000_000_000
class TelegramUploader:
    name="telegram"
    def __init__(self, api_id=None, api_hash=None, session="javdl", bot_token=None):
        self.app=Client(session, api_id=int(api_id or os.environ["TELEGRAM_API_ID"]), api_hash=api_hash or os.environ["TELEGRAM_API_HASH"], bot_token=bot_token or os.getenv("TELEGRAM_BOT_TOKEN"))
    @staticmethod
    def split_if_needed(file_path, limit=TELEGRAM_LIMIT):
        p=Path(file_path)
        if p.stat().st_size <= limit: return [str(p)]
        import subprocess
        # Split on keyframe-safe boundaries using ffmpeg; resulting parts stay below the limit.
        probe=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(p)],text=True).strip()
        duration=float(probe); parts=math.ceil(p.stat().st_size/limit); segment=duration/parts; out=[]
        for i in range(parts):
            target=p.with_name(f"{p.stem}.part{i+1}{p.suffix}")
            subprocess.run(["ffmpeg","-y","-ss",str(i*segment),"-i",str(p),"-t",str(segment),"-c","copy",str(target)],check=True)
            out.append(str(target))
        return out
    def upload(self,file_path,chat_id,caption="",thumbnail=None,duration=None,progress=None):
        paths=self.split_if_needed(file_path)
        results=[]
        with self.app:
            for i,path in enumerate(paths,1):
                part_caption=caption if len(paths)==1 else f"{caption}\n\nPart {i}/{len(paths)}"
                results.append(self.app.send_video(chat_id,path,caption=part_caption,thumb=thumbnail,duration=int(duration or 0),supports_streaming=True,progress=self._progress(progress)))
        return results
    @staticmethod
    def _progress(callback):
        if not callback: return None
        def cb(current,total): callback(current,total,"telegram_upload")
        return cb
