"""fpp CLI — control Falcon Player from the command line."""

from __future__ import annotations

import json
import mimetypes
import os
import random
import time
from pathlib import Path

import click

from .client import FPPClient

DEFAULT_HOST = os.environ.get("FPP_HOST", "192.168.1.66")


def _client(host: str) -> FPPClient:
    return FPPClient(host)


def _print(obj) -> None:
    click.echo(json.dumps(obj, indent=2))


@click.group()
@click.option("--host", default=DEFAULT_HOST, envvar="FPP_HOST", show_default=True,
              help="FPP device IP or hostname")
@click.pass_context
def main(ctx: click.Context, host: str) -> None:
    """Control a Falcon Player (FPP) device."""
    ctx.ensure_object(dict)
    ctx.obj["host"] = host


# ------------------------------------------------------------------ status

@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current playback status."""
    with _client(ctx.obj["host"]) as fpp:
        _print(fpp.status())


@main.command("info")
@click.pass_context
def system_info(ctx: click.Context) -> None:
    """Show FPP system info."""
    with _client(ctx.obj["host"]) as fpp:
        _print(fpp.system_info())


# --------------------------------------------------------------- playlists

@main.command("play")
@click.argument("playlist")
@click.option("--repeat", is_flag=True, default=False, help="Loop the playlist")
@click.pass_context
def play_playlist(ctx: click.Context, playlist: str, repeat: bool) -> None:
    """Start a playlist."""
    with _client(ctx.obj["host"]) as fpp:
        _print(fpp.start_playlist(playlist, repeat))


@main.command("stop")
@click.option("--graceful", is_flag=True, default=False,
              help="Finish current item before stopping")
@click.pass_context
def stop_playback(ctx: click.Context, graceful: bool) -> None:
    """Stop playback."""
    with _client(ctx.obj["host"]) as fpp:
        result = fpp.stop_gracefully() if graceful else fpp.stop()
        _print(result)


@main.command("playlists")
@click.pass_context
def list_playlists(ctx: click.Context) -> None:
    """List all playlists on the device."""
    with _client(ctx.obj["host"]) as fpp:
        _print(fpp.list_playlists())


# --------------------------------------------------------------- upload

def _file_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        if mime.startswith("image/"):
            return "images"
        if mime.startswith("video/"):
            return "videos"
    if path.suffix.lower() == ".fseq":
        return "sequences"
    raise click.ClickException(f"Cannot determine file type for {path.name}")


@main.command("upload")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def upload(ctx: click.Context, path: Path) -> None:
    """Upload a file or folder to FPP.

    PATH can be a single file or a directory. For directories, all
    supported files are uploaded and a playlist is created matching
    the folder name.
    """
    host = ctx.obj["host"]
    if path.is_dir():
        _upload_folder(host, path)
    else:
        _upload_single(host, path)


def _upload_single(host: str, path: Path) -> None:
    file_type = _file_type(path)
    if file_type == "videos":
        _warn_if_video_too_small(path)
    data = path.read_bytes()
    with _client(host) as fpp:
        fpp.upload_file(file_type, path.name, data)
    click.echo(f"Uploaded {path.name} → {file_type}/")


def _probe(path: Path, entries: str) -> dict:
    """Read stream fields from a media file via ffprobe. Empty dict if unavailable."""
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", entries, "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    merged: dict = {}
    for stream in data.get("streams", []):
        merged.update(stream)
    merged.update(data.get("format", {}))
    return merged


def _video_duration(path: Path) -> int:
    """Duration in whole seconds, rounded up. 0 when it cannot be determined."""
    import math

    info = _probe(path, "format=duration")
    try:
        return max(0, math.ceil(float(info["duration"])))
    except (KeyError, TypeError, ValueError):
        return 0


# FPP decodes video through SDLOut/ffmpeg and then scales to the matrix itself.
# Frames below this size make its H.264 decoder fail with "Invalid NAL unit size",
# which spins a tight error loop that floods fppd.log and wedges the API.
# Upload a larger source and let FPP do the downscale.
MIN_VIDEO_DIMENSION = 256


def _warn_if_video_too_small(path: Path) -> None:
    info = _probe(path, "stream=width,height")
    try:
        w, h = int(info["width"]), int(info["height"])
    except (KeyError, TypeError, ValueError):
        return
    if min(w, h) < MIN_VIDEO_DIMENSION:
        click.secho(
            f"  WARNING: {path.name} is {w}x{h}. FPP's decoder fails on frames "
            f"smaller than {MIN_VIDEO_DIMENSION}px and will flood fppd.log until "
            f"fppd is restarted. Upload a larger version and let FPP scale it "
            f"down to the panel.",
            fg="yellow", err=True,
        )


def _upload_folder(host: str, folder: Path) -> None:
    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and not f.name.startswith(".")
    )
    uploaded: list[dict] = []
    with _client(host) as fpp:
        for f in files:
            try:
                file_type = _file_type(f)
            except click.ClickException:
                click.echo(f"Skipping {f.name} (unknown type)", err=True)
                continue
            if file_type == "videos":
                _warn_if_video_too_small(f)
            fpp.upload_file(file_type, f.name, f.read_bytes())
            uploaded.append({"type": file_type, "name": f.name, "path": f})
            click.echo(f"  Uploaded {f.name} → {file_type}/")

        if uploaded:
            playlist_name = folder.name
            _create_playlist(fpp, playlist_name, uploaded)
            click.echo(f"Created playlist: {playlist_name}")


def _create_playlist(fpp: FPPClient, name: str, files: list[dict]) -> None:
    """Build and save a playlist from uploaded files via SSH."""
    import json as _json
    import subprocess

    entries = []
    for f in files:
        if f["type"] == "images":
            entries.append({
                "type": "image",
                "enabled": 1,
                "playOnce": 0,
                "imagePath": f["name"],
                "modelName": "LED Panels",
                "displayMode": "argsOnly",
                "duration": 5,
            })
        elif f["type"] == "videos":
            # FPP 9.5.2 writes video entries as type "media" with mediaName —
            # NOT type "video"/videoName. Verified against a playlist created by
            # the FPP UI itself; the old shape produced a playlist FPP would not play.
            entries.append({
                "type": "media",
                "enabled": 1,
                "playOnce": 0,
                "fileMode": "single",
                "mediaName": f["name"],
                "videoOut": "--Default--",
                "displayMode": "argsOnly",
                "timecode": "Default",
                "duration": _video_duration(f["path"]) if f.get("path") else 0,
            })
        elif f["type"] == "sequences":
            entries.append({
                "type": "sequence",
                "enabled": 1,
                "playOnce": 0,
                "sequenceName": f["name"],
            })

    playlist = {
        "name": name,
        "version": 4,
        "repeat": 1,
        "loopCount": 0,
        "desc": "",
        "random": 0,
        "empty": False,
        "leadIn": [],
        "mainPlaylist": entries,
        "leadOut": [],
    }
    pl_json = _json.dumps(playlist, indent=4)
    host = fpp._base.removeprefix("http://").removeprefix("https://")
    subprocess.run(
        ["ssh", f"fpp@{host}",
         f"cat > /home/fpp/media/playlists/{name}.json"],
        input=pl_json.encode(),
        check=True,
    )


# --------------------------------------------------------------- sequences

@main.command("sequence")
@click.argument("name")
@click.option("--start-at", default=0, show_default=True, help="Start offset in seconds")
@click.pass_context
def play_sequence(ctx: click.Context, name: str, start_at: int) -> None:
    """Play a sequence file directly."""
    with _client(ctx.obj["host"]) as fpp:
        _print(fpp.start_sequence(name, start_at))


# --------------------------------------------------------------- cleanup

@main.command("cleanup")
@click.argument("playlist")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be deleted without deleting")
@click.pass_context
def cleanup(ctx: click.Context, playlist: str, dry_run: bool) -> None:
    """Delete a playlist and all files it references.

    Prevents orphaned files on the device.
    """
    host = ctx.obj["host"]
    with _client(host) as fpp:
        # Fetch playlist details
        try:
            pl = fpp._get(f"/playlist/{playlist}")
        except Exception as e:
            raise click.ClickException(f"Could not fetch playlist '{playlist}': {e}")

        all_entries = (
            pl.get("leadIn", [])
            + pl.get("mainPlaylist", [])
            + pl.get("leadOut", [])
        )

        # FPP entry shapes: images use type "image" + imagePath; video/audio use
        # type "media" + mediaName ("video" kept for any hand-written legacy entries).
        files_to_delete: list[tuple[str, str]] = []
        for entry in all_entries:
            t = entry.get("type", "")
            if t == "image":
                name = entry.get("imagePath") or entry.get("mediaName", "")
                dirname = "images"
            elif t in ("media", "video"):
                name = entry.get("mediaName") or entry.get("videoName", "")
                dirname = "videos"
            elif t == "sequence":
                name = entry.get("sequenceName", "")
                dirname = "sequences"
            else:
                continue
            if name:
                files_to_delete.append((dirname, name))

        if dry_run:
            click.echo(f"Would delete playlist: {playlist}")
            for ft, fn in files_to_delete:
                click.echo(f"  Would delete {ft}/{fn}")
            return

        for ft, fn in files_to_delete:
            try:
                resp = fpp._http.delete(f"/file/{ft}/{fn}")
                resp.raise_for_status()
                click.echo(f"  Deleted {ft}/{fn}")
            except Exception as e:
                click.echo(f"  Failed to delete {ft}/{fn}: {e}", err=True)

        try:
            resp = fpp._http.delete(f"/playlist/{playlist}")
            resp.raise_for_status()
            click.echo(f"Deleted playlist: {playlist}")
        except Exception as e:
            raise click.ClickException(f"Failed to delete playlist '{playlist}': {e}")


@main.command("orphans")
@click.pass_context
def orphans(ctx: click.Context) -> None:
    """List files on the device not referenced by any playlist."""
    with _client(ctx.obj["host"]) as fpp:
        playlists = fpp.list_playlists()
        referenced: set[str] = set()
        for pl_name in playlists:
            try:
                pl = fpp._get(f"/playlist/{pl_name}")
            except Exception:
                continue
            for entry in (
                pl.get("leadIn", [])
                + pl.get("mainPlaylist", [])
                + pl.get("leadOut", [])
            ):
                # cover every entry shape: media/video, image, sequence
                for key in ("mediaName", "videoName", "imagePath", "sequenceName"):
                    name = entry.get(key)
                    if name:
                        referenced.add(name)

        # /api/media returns a flat list of filenames on FPP 9.5.2; older/other
        # builds have been seen returning a dict keyed by category.
        media = fpp.list_media()
        all_files: list[str] = []
        if isinstance(media, dict):
            for category in ("images", "videos", "sequences"):
                all_files.extend(media.get(category, []) or [])
        elif isinstance(media, list):
            all_files.extend(m for m in media if isinstance(m, str))

        orphan_files = [f for f in all_files if f not in referenced]
        if orphan_files:
            click.echo("Orphaned files (not in any playlist):")
            for f in orphan_files:
                click.echo(f"  {f}")
        else:
            click.echo("No orphaned files found.")


# --------------------------------------------------------------- image playlist

@main.command("create-image-playlist")
@click.argument("name")
@click.argument("path", type=click.Path(exists=True))
@click.option("--pause", default=3.0, show_default=True, metavar="SECONDS",
              help="Pause duration between images")
@click.option("--seed", default=None, type=int, help="Random seed for reproducible shuffle")
@click.pass_context
def create_image_playlist(ctx: click.Context, name: str, path: str, pause: float, seed) -> None:
    """Upload images from PATH, shuffle them, and create a playlist called NAME.

    Each image is followed by a pause of PAUSE seconds.
    """
    host = ctx.obj["host"]
    path = Path(path)

    images = sorted(
        f for f in path.iterdir()
        if f.is_file() and not f.name.startswith(".")
        and mimetypes.guess_type(str(f))[0] in (
            "image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"
        )
    )
    if not images:
        raise click.ClickException(f"No image files found in {path}")

    rng = random.Random(seed)
    rng.shuffle(images)
    click.echo(f"Found {len(images)} images — uploading and creating playlist '{name}'")

    entries: list[dict] = []
    with _client(host) as fpp:
        for img in images:
            fpp.upload_file("images", img.name, img.read_bytes())
            click.echo(f"  uploaded {img.name}")
            entries.append({
                "type": "image",
                "enabled": 1,
                "playOnce": 0,
                "imagePath": img.name,
                "modelName": "LED Panels",
                "displayMode": "argsOnly",
            })
            entries.append({
                "type": "pause",
                "enabled": 1,
                "playOnce": 0,
                "duration": pause,
                "displayMode": "argsOnly",
            })

        import json as _json
        import subprocess
        playlist = {
            "name": name,
            "version": 4,
            "repeat": 1,
            "loopCount": 0,
            "desc": "",
            "random": 0,
            "empty": False,
            "leadIn": [],
            "mainPlaylist": entries,
            "leadOut": [],
        }
        pl_json = _json.dumps(playlist, indent=4)
        subprocess.run(
            ["ssh", f"fpp@{host.removeprefix('http://').removeprefix('https://')}",
             f"cat > /home/fpp/media/playlists/{name}.json"],
            input=pl_json.encode(),
            check=True,
        )
    click.echo(f"Created playlist '{name}' with {len(images)} images ({pause}s pause each)")


# --------------------------------------------------------------- tv slideshow

HA_URL = os.environ.get("HA_URL", "http://192.168.1.73:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
HA_TV_ENTITY = os.environ.get("HA_TV_ENTITY", "media_player.samsung_the_frame_75")


@main.command("tv-slideshow")
@click.argument("path", type=click.Path(exists=True))
@click.option("--pause", default=5.0, show_default=True, metavar="SECONDS",
              help="Seconds each image is shown")
@click.option("--token", default=None, envvar="HA_TOKEN", help="HA long-lived access token")
@click.option("--ha-url", default=HA_URL, show_default=True, envvar="HA_URL")
@click.option("--entity", default=HA_TV_ENTITY, show_default=True, envvar="HA_TV_ENTITY")
@click.option("--host-ip", default="192.168.1.247", show_default=True,
              help="This machine's LAN IP (so the TV can reach the image server)")
@click.option("--port", default=8765, show_default=True, help="Local HTTP server port")
@click.option("--seed", default=None, type=int, help="Random seed for shuffle")
@click.pass_context
def tv_slideshow(ctx: click.Context, path: str, pause: float, token: str, ha_url: str,
                 entity: str, host_ip: str, port: int, seed) -> None:
    """Serve images from PATH over HTTP and play them as a slideshow on the TV.

    Images are shuffled randomly and cycled continuously until Ctrl+C.
    """
    import threading
    import http.server
    import functools

    if not token:
        raise click.ClickException("HA token required — pass --token or set HA_TOKEN env var")

    folder = Path(path)
    images = [
        f for f in folder.iterdir()
        if f.is_file() and not f.name.startswith(".")
        and mimetypes.guess_type(f.name)[0] in (
            "image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"
        )
    ]
    if not images:
        raise click.ClickException(f"No images found in {path}")

    rng = random.Random(seed)
    rng.shuffle(images)
    click.echo(f"Found {len(images)} images — starting HTTP server on :{port}")

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(folder),
    )
    server = http.server.HTTPServer(("", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _play(filename: str) -> None:
        url = f"http://{host_ip}:{port}/{filename}"
        body = json.dumps({
            "entity_id": entity,
            "media_content_id": url,
            "media_content_type": "image/jpeg",
        })
        import urllib.request
        req = urllib.request.Request(
            f"{ha_url}/api/services/media_player/play_media",
            data=body.encode(),
            headers=headers,
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            click.echo(f"  HA error: {e}", err=True)

    click.echo(f"Showing slideshow on {entity} ({pause}s each) — Ctrl+C to stop")
    try:
        idx = 0
        while True:
            img = images[idx % len(images)]
            click.echo(f"  [{idx+1}/{len(images)}] {img.name}")
            _play(img.name)
            time.sleep(pause)
            idx += 1
            if idx % len(images) == 0:
                rng.shuffle(images)
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        server.shutdown()


# --------------------------------------------------------------- scoreboard

_SCOREBOARD_PLAYLIST = "fpp-scoreboard"


@main.command("scoreboard")
@click.option(
    "--league",
    default="epl",
    show_default=True,
    type=click.Choice(["epl", "ucl", "all"]),
    help="League to display (epl, ucl, or all)",
)
@click.option(
    "--interval",
    default=15,
    show_default=True,
    type=float,
    metavar="SECONDS",
    help="Seconds each game is shown before cycling to the next.",
)
@click.option(
    "--max-cards",
    default=12,
    show_default=True,
    type=int,
    help="Cap on cards per cycle. A whole matchday plus fixtures runs long.",
)
@click.option(
    "--refresh",
    default=60,
    show_default=True,
    type=float,
    metavar="SECONDS",
    help="Minimum seconds between refetches when nothing is live.",
)
@click.pass_context
def scoreboard(ctx: click.Context, league: str, interval: float,
               max_cards: int, refresh: float) -> None:
    """Display a live soccer scoreboard on the LED panel.

    Each card is one game: club colours and shields, the score if it is live or
    finished, and WHEN BOTH OF THOSE TEAMS PLAY NEXT.

    When no game is in progress — which is most of the time, since a league
    plays about six hours a week — it falls back to the most recent matchday's
    results followed by the next matchday's fixtures, so the panel is still
    saying something at 3am on a Wednesday.

    Renders each card as a JPEG, uploads to FPP, and plays them as a looping
    playlist, rebuilt on each full cycle.
    """
    from .displays.soccer import (
        LEAGUES, attach_next, fetch_fixtures, render_no_games, render_scoreboard,
        select_cards,
    )

    host = ctx.obj["host"]
    keys = list(LEAGUES) if league == "all" else [league]

    def _fetch() -> tuple[list[dict], str]:
        games, reason = select_cards(keys, max_cards=max_cards)
        # Next fixtures come from a wider net than the cards do: a Premier
        # League side's next match is often a European one, and answering
        # "when do they play next" with the wrong competition is worse than
        # not answering.
        try:
            attach_next(games, fetch_fixtures(list(LEAGUES)))
        except Exception as exc:
            click.echo(f"  (no next-fixture data: {exc})")
        return games, reason

    def _build_and_play(fpp: FPPClient, games: list[dict]) -> None:
        """Upload rendered frames and (re)start the scoreboard playlist."""
        entries = []

        def _image_entry(filename: str) -> dict:
            return {
                "type": "image",
                "enabled": 1,
                "playOnce": 0,
                "imagePath": filename,
                "modelName": "LED Panels",
                "displayMode": "argsOnly",
            }

        def _pause_entry(secs: float) -> dict:
            return {"type": "pause", "enabled": 1, "playOnce": 0, "duration": secs, "displayMode": "argsOnly"}

        if not games:
            img_name = "fpp-scoreboard-0.jpg"
            data = render_no_games(league if league != "all" else "epl").to_image_bytes()
            fpp.upload_file("images", img_name, data)
            entries += [_image_entry(img_name), _pause_entry(interval)]
        else:
            for i, game in enumerate(games):
                img_name = f"fpp-scoreboard-{i}.jpg"
                data = render_scoreboard(game).to_image_bytes()
                fpp.upload_file("images", img_name, data)
                label = f"{game['away_abbr']} {game['away_score']}–{game['home_score']} {game['home_abbr']}"
                click.echo(f"  uploaded [{game['league_label']}] {label}")
                entries += [_image_entry(img_name), _pause_entry(interval)]

        import json as _json
        playlist = {
            "name": _SCOREBOARD_PLAYLIST,
            "version": 4,
            "repeat": 1,
            "loopCount": 0,
            "desc": "",
            "random": 0,
            "empty": False,
            "leadIn": [],
            "mainPlaylist": entries,
            "leadOut": [],
        }
        # Via _write_playlist_json, which writes the file directly when we are
        # already ON the device. This runs as a systemd unit there with
        # --host 127.0.0.1, and the old inline ssh call meant the scoreboard
        # service could only work if the box could SSH to itself.
        _write_playlist_json(host, _SCOREBOARD_PLAYLIST, _json.dumps(playlist, indent=4))
        fpp.start_playlist(_SCOREBOARD_PLAYLIST, repeat=True)

    _REASONS = {
        "live":  "live now",
        "today": "today's games",
        "idle":  "last results + next fixtures",
    }

    click.echo(f"Fetching scores ({league.upper()})...")
    try:
        while True:
            games, reason = _fetch()
            n = len(games)
            click.echo(f"Building scoreboard — {n} card{'s' if n != 1 else ''} "
                       f"[{_REASONS.get(reason, reason)}]  ({interval}s each)")
            with _client(host) as fpp:
                _build_and_play(fpp, games)

            cycle_secs = max(len(games), 1) * interval
            # Nothing is live: results and fixtures do not change minute to
            # minute, so do not hammer ESPN once a short cycle comes round.
            if reason != "live":
                cycle_secs = max(cycle_secs, refresh)
            click.echo(f"Playing — next refresh in {cycle_secs:.0f}s  (Ctrl+C to stop)")
            time.sleep(cycle_secs)

            click.echo("Refreshing scores...")

    except KeyboardInterrupt:
        click.echo("\nStopped.")


# --------------------------------------------------------------- world clock

_WORLDCLOCK_PLAYLIST = "fpp-worldclock"  # base name; "-a"/"-b" suffix alternates each cycle


def _write_playlist_json(host: str, name: str, pl_json: str) -> None:
    """Write a playlist JSON to the FPP media dir — locally if we're on the device, else via SSH."""
    if host in ("127.0.0.1", "localhost"):
        Path(f"/home/fpp/media/playlists/{name}.json").write_text(pl_json)
    else:
        import subprocess
        # -T and a swallowed stderr: without them the device MOTD ("Raspbian
        # GNU/Linux 12", "Falcon Player OS Image...") lands in the middle of a
        # display loop's own output every cycle and reads like an error.
        subprocess.run(
            ["ssh", "-T", "-o", "LogLevel=ERROR", f"fpp@{host}",
             f"cat > /home/fpp/media/playlists/{name}.json"],
            input=pl_json.encode(),
            check=True,
            stderr=subprocess.DEVNULL,
        )


@main.command("worldclock")
@click.option(
    "--interval",
    default=15,
    show_default=True,
    type=float,
    metavar="SECONDS",
    help="Seconds each city is shown before paging to the next.",
)
@click.option(
    "--count",
    default=6,
    show_default=True,
    type=int,
    metavar="N",
    help="Number of cities randomly picked each loop.",
)
@click.option("--seed", default=None, type=int, help="Random seed for reproducible city picks")
@click.pass_context
def worldclock(ctx: click.Context, interval: float, count: int, seed) -> None:
    """Display a rotating world clock: local time, weather, and skyline per city.

    Each loop, COUNT cities are picked at random from the full city pool and
    shown for INTERVAL seconds each. A new random set is picked every loop.

    Image files and playlists are reused across two alternating sets ("a"
    and "b") — a loop always renders into the set that isn't currently on
    screen, so files already playing are never overwritten mid-display, and
    the device only ever holds two batches of images (no disk growth).
    """
    from .displays.worldclock import CITIES, fetch_weather, render_city

    host = ctx.obj["host"]
    rng = random.Random(seed)
    count = min(count, len(CITIES))

    def _image_entry(filename: str) -> dict:
        return {
            "type": "image",
            "enabled": 1,
            "playOnce": 0,
            "imagePath": filename,
            "modelName": "LED Panels",
            "displayMode": "argsOnly",
        }

    def _pause_entry(secs: float) -> dict:
        return {"type": "pause", "enabled": 1, "playOnce": 0, "duration": secs, "displayMode": "argsOnly"}

    def _build_and_play(fpp: FPPClient, buf: str) -> list[str]:
        """Render+upload the next batch into buffer 'a' or 'b' and switch playback to it."""
        cities = rng.sample(CITIES, count)
        entries = []
        picked = []
        for i, city in enumerate(cities):
            weather = fetch_weather(city)
            img_name = f"fpp-worldclock-{buf}-{i}.jpg"
            data = render_city(city, weather).to_image_bytes()
            fpp.upload_file("images", img_name, data)
            click.echo(f"  [{buf}] {city['name']} — {weather.get('condition', '?')}")
            entries += [_image_entry(img_name), _pause_entry(interval)]
            picked.append(city["name"])

        import json as _json
        playlist_name = f"{_WORLDCLOCK_PLAYLIST}-{buf}"
        playlist = {
            "name": playlist_name,
            "version": 4,
            "repeat": 1,
            "loopCount": 0,
            "desc": "",
            "random": 0,
            "empty": False,
            "leadIn": [],
            "mainPlaylist": entries,
            "leadOut": [],
        }
        _write_playlist_json(host, playlist_name, _json.dumps(playlist, indent=4))
        fpp.start_playlist(playlist_name, repeat=True)
        return picked

    click.echo(f"World clock — {count} random cities per loop  ({interval}s each)")
    try:
        buf = "a"
        while True:
            with _client(host) as fpp:
                picked = _build_and_play(fpp, buf)

            cycle_secs = count * interval
            click.echo(f"Playing {', '.join(picked)} — next pick in {cycle_secs:.0f}s  (Ctrl+C to stop)")
            time.sleep(cycle_secs)
            buf = "b" if buf == "a" else "a"

    except KeyboardInterrupt:
        click.echo("\nStopped.")
