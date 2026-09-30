from pathlib import Path
import subprocess


def clip_video(
    source: str,
    clips: list[tuple[str, str]],
    output_dir="clips",
) -> list[str]:
    """Create the user-selected clips.

    Clipping is only called when the job explicitly contains clip ranges.
    """
    if not clips:
        return [source]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []

    for index, (start, end) in enumerate(clips, 1):
        if not start or not end:
            raise ValueError("Each clip needs a start and end time.")

        target = out / f"clip_{index:02d}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                source,
                "-c",
                "copy",
                str(target),
            ],
            check=True,
        )
        results.append(str(target))

    return results
