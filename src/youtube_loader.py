"""Download and clean YouTube subtitles from a channel."""

import json
import logging
import re
import subprocess
from pathlib import Path

from src.config import SUBTITLES_DIR

logger = logging.getLogger(__name__)

# All video IDs from https://www.youtube.com/@a.dmitrov
CHANNEL_VIDEO_IDS = [
    "zn4T_DopwJA",  # IS THERE A LINDEN? Full version.
    "T5pfZFxU2a4",  # РОЙ.ПОЛНАЯ ВЕРСИЯ
    "Wd39uuHR5dw",  # ЛИПА 72% МЁД С Усадьбы Дмитровых
    "A7KbMz1yOsc",  # Preparation and extraction of honey.
    "dmE2RGJfKKg",  # Bees are getting ready for winter.
    "9_jm7WVuiEA",  # STOP AND ADMIRE THE BEAUTY
    "t5smCzAuLPc",  # Convenient beekeeper's box.
    "co_tcssSdHc",  # Здоровье за ваши деньги.
    "7dV5KE84y-c",  # Дом на 12 рамок для моих пчёлок
    "8ZMHcuotrkY",  # ЦВЕТЫ СОЛНЦА ДЛЯ ЗДОРОВЬЯ
    "2HpiM2j2Wyg",  # Польза одуванчика для пчёл.
    "Nrz0hFJ8hwI",  # Наващиваю свою вощину.
    "4FULfYjcDwA",  # Cast candles made of pure wax.
    "uXvie6X91E4",  # Здоровье почек.
    "CQk8B8TcV6U",  # Propolis tincture on moonshine.
    "i90wYHmdzdQ",  # Пасека и пруды на 50млн (90 мин интервью)
    "4Wmv8n8d_2w",  # Healthy and tasty. Baked apples with honey.
    "RYRsE-7XarY",  # Рецепт для суставов и пищеварения
    "KAGu7qtkfKY",  # Making cast wax foundation at home.
    "IKiqRbEM4S8",  # Достаю и режу медовый сот.
    "YAy2yI-niVI",  # Как я делаю крем мёд.
    "sibUB47xNvU",  # Липовые мини рамки для сотового мёда.
    "s5I6gRfb4Y0",  # Our estate. Spring 2022.
    "IytsyZtH5pM",  # Этапы строительства.Дом для пчёл и пчеловода.
    "cqCCBl3LMgk",  # Матководство. Стартер. Прививочный ящик.
    "k0GtIz2lFC8",  # Подземный зимовник.
    "33959STmkmM",  # Cascade ponds. View from above, winter.
]


def fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript for a single video using youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=["ru"])
        text = " ".join(snippet.text for snippet in transcript)
        # Clean up auto-generated artifacts
        text = re.sub(r"\[музыка\]|\[аплодисменты\]|\[Music\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) > 50 else None
    except Exception as e:
        logger.warning(f"Failed to fetch transcript for {video_id}: {e}")
        return None


def download_all_subtitles(
    video_ids: list[str] | None = None,
    output_dir: Path | None = None,
) -> list[dict]:
    """Download subtitles for all videos and return cleaned texts."""
    video_ids = video_ids or CHANNEL_VIDEO_IDS
    output_dir = output_dir or SUBTITLES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for video_id in video_ids:
        text = fetch_transcript(video_id)
        if text:
            txt_path = output_dir / f"{video_id}.txt"
            txt_path.write_text(text, encoding="utf-8")
            results.append({
                "video_id": video_id,
                "source": f"youtube:{video_id}",
                "text": text,
                "path": str(txt_path),
            })
            logger.info(f"OK: {video_id} ({len(text)} chars)")
        else:
            logger.warning(f"SKIP: {video_id} (no subtitles)")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    docs = download_all_subtitles()
    print(f"\nProcessed {len(docs)} / {len(CHANNEL_VIDEO_IDS)} videos with subtitles")
    total_chars = sum(len(d["text"]) for d in docs)
    print(f"Total text: {total_chars:,} characters")
    for doc in docs:
        print(f"  {doc['video_id']}: {len(doc['text']):,} chars")
