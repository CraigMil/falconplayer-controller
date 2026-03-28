"""fpp CLI — control Falcon Player from the command line."""

from __future__ import annotations

import json
import mimetypes
import os
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
    data = path.read_bytes()
    with _client(host) as fpp:
        fpp.upload_file(file_type, path.name, data)
    click.echo(f"Uploaded {path.name} → {file_type}/")


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
            fpp.upload_file(file_type, f.name, f.read_bytes())
            uploaded.append({"type": file_type, "name": f.name})
            click.echo(f"  Uploaded {f.name} → {file_type}/")

        if uploaded:
            playlist_name = folder.name
            _create_playlist(fpp, playlist_name, uploaded)
            click.echo(f"Created playlist: {playlist_name}")


def _create_playlist(fpp: FPPClient, name: str, files: list[dict]) -> None:
    """Build and save a playlist from uploaded files via the FPP API."""
    entries = []
    for f in files:
        if f["type"] == "images":
            entries.append({"type": "image", "mediaName": f["name"], "duration": 5})
        elif f["type"] == "videos":
            entries.append({"type": "video", "mediaName": f["name"]})
        elif f["type"] == "sequences":
            entries.append({"type": "sequence", "sequenceName": f["name"]})

    playlist = {
        "name": name,
        "mainPlaylist": entries,
        "leadIn": [],
        "leadOut": [],
        "repeat": 0,
    }
    resp = fpp._http.post(f"/playlist/{name}", json=playlist)
    resp.raise_for_status()


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

        files_to_delete: list[tuple[str, str]] = []
        for entry in all_entries:
            t = entry.get("type", "")
            if t == "image":
                files_to_delete.append(("images", entry.get("mediaName", "")))
            elif t == "video":
                files_to_delete.append(("videos", entry.get("mediaName", "")))
            elif t == "sequence":
                files_to_delete.append(("sequences", entry.get("sequenceName", "")))

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
                name = entry.get("mediaName") or entry.get("sequenceName") or ""
                if name:
                    referenced.add(name)

        media = fpp.list_media()
        all_files: list[str] = []
        for category in ("images", "videos", "sequences"):
            all_files.extend(media.get(category, []))

        orphan_files = [f for f in all_files if f not in referenced]
        if orphan_files:
            click.echo("Orphaned files (not in any playlist):")
            for f in orphan_files:
                click.echo(f"  {f}")
        else:
            click.echo("No orphaned files found.")
