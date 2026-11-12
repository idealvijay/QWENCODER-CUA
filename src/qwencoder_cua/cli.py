from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print

from qwencoder_cua import (
    Computer, OllamaTaskPlanner, TaskPlan, TaskPolicy, TaskRunner, __version__,
)
from qwencoder_cua.core.exceptions import CUAError

app = typer.Typer(help="QWENCODER CUA local desktop automation")


@app.command()
def version():
    print(f"QWENCODER CUA {__version__}")


@app.command()
def doctor():
    """Run platform dependency diagnostics."""
    import runpy
    # cli.py is <repo>/src/qwencoder_cua/cli.py, so parents[2] is the repo root.
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "doctor.py"))


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


def _approval_prompt(step, number: int) -> bool:
    return typer.confirm(
        f"Approve step {number}: {step.action} ({step.step_id})?",
        default=False,
    )


@app.command("run-plan")
def run_plan(
    plan_file: Path = typer.Argument(..., exists=True, readable=True),
    max_steps: int = typer.Option(15, min=1, max=50),
):
    """Execute a reviewed JSON plan. Steps marked approval_required prompt before dispatch."""
    plan = TaskPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    with Computer() as computer:
        result = TaskRunner(computer, TaskPolicy(max_steps=max_steps)).execute(
            plan, approve=_approval_prompt
        )
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    if not result.success:
        raise typer.Exit(code=1)


@app.command("run-goal")
def run_goal(
    goal: str = typer.Argument(...),
    model: str | None = typer.Option(None, "--model", help="Ollama model; defaults to MODEL or minicpm-v4.5:q4_0."),
    max_steps: int = typer.Option(12, min=1, max=30),
):
    """Run an observe/plan/act/verify loop using the local Ollama server."""
    planner = OllamaTaskPlanner(model=model)
    try:
        with Computer() as computer:
            result = TaskRunner(computer, TaskPolicy(max_steps=max_steps)).run(
                goal, planner, approve=_approval_prompt
            )
    except CUAError as exc:
        print(f"[red]QWENCODER error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
