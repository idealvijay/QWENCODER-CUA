from pathlib import Path
import typer
from rich import print

from qwencoder_cua.core.computer import Computer
from qwencoder_cua.core.registry import detect_linux_session

app = typer.Typer(help="QWENCODER local computer-use driver")


@app.command()
def doctor():
    import platform
    print(f"[bold]Platform:[/bold] {platform.system()}")
    if platform.system() == "Linux":
        print(f"[bold]Session:[/bold] {detect_linux_session()}")
    try:
        with Computer() as computer:
            print(f"[green]Driver connected:[/green] {computer.driver.name}")
            print(f"Capabilities: {computer.driver.capabilities.model_dump()}")
    except Exception as exc:
        print(f"[red]Driver unavailable:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def screenshot(output: Path = typer.Option(Path("qwencoder-desktop.png"), "--output", "-o")):
    with Computer() as computer:
        image = computer.screenshot(output)
    print(f"[green]Saved:[/green] {output} ({image.width}x{image.height})")


@app.command()
def windows():
    with Computer() as computer:
        for item in computer.windows():
            print(f"{item.id:>12}  {item.title}")
