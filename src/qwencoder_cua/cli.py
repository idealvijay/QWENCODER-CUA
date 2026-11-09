from __future__ import annotations
import json
from pathlib import Path
import typer
from rich import print
from qwencoder_cua import Computer, __version__

app = typer.Typer(help="QWENCODER CUA local desktop automation")

@app.command()
def version():
    print(f"QWENCODER CUA {__version__}")

@app.command()
def doctor():
    """Run platform dependency diagnostics."""
    import runpy
    runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts" / "doctor.py"))

@app.command()
def screenshot(output: str = typer.Option("desktop.png", "--output", "-o")):
    with Computer() as computer:
        computer.screenshot(output)
    print(f"[green]Saved screenshot:[/green] {output}")

@app.command()
def windows():
    with Computer(accessibility=False) as computer:
        for window in computer.windows():
            print(f"{window.id}\t{window.title}")

@app.command("inspect")
def inspect_tree(max_depth: int = typer.Option(10, min=1, max=30)):
    """Capture screenshot and dump normalized accessibility elements."""
    with Computer() as computer:
        observation = computer.observe(max_depth=max_depth)
        print(json.dumps(observation.model_dump(mode="json"), indent=2, default=str))

@app.command("portal-status")
def portal_status():
    """Probe Wayland portal readiness without requesting desktop permissions."""
    from qwencoder_cua.drivers.linux.wayland_portal import probe_wayland_portals
    print(json.dumps(probe_wayland_portals().__dict__, indent=2))

if __name__ == "__main__":
    app()
