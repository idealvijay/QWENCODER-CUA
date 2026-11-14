from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print

from qwencoder_cua import (
    Computer, OllamaTaskPlanner, TaskPlan, TaskPolicy, TaskRunner, __version__,
)
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.window import WindowInfo, WindowSelector

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


def _window_selector(window_id, process_name, window_title):
    if not any((window_id, process_name, window_title)):
        return None
    return WindowSelector(
        window_id=window_id,
        process_name=process_name,
        title_contains=window_title,
    )


_DRAWING_GOAL_TERMS = (
    "draw", "drawing", "sketch", "circle", "ellipse", "shape",
    "canvas", "brush", "pencil", "paint",
)


def _auto_paint_window_selector(
    goal: str,
    windows: list[WindowInfo],
    active_window: WindowInfo | None,
) -> WindowSelector | None:
    """Auto-bind Paint for drawing goals when an unambiguous visible Paint window exists."""
    normalized_goal = goal.casefold()
    if not any(term in normalized_goal for term in _DRAWING_GOAL_TERMS):
        return None

    paint_windows = [
        window for window in windows
        if (window.process_name or "").casefold() == "mspaint.exe"
        and window.visible
        and not window.minimized
    ]
    if not paint_windows:
        return None

    if len(paint_windows) == 1:
        # Process identity survives a changed HWND during task execution.
        return WindowSelector(process_name="mspaint.exe")

    # Multiple Paint windows are common. Prefer the one already in the foreground,
    # otherwise fail safely rather than guessing which document the user intended.
    active_paint = next(
        (window for window in paint_windows
         if active_window is not None and window.id == active_window.id),
        None,
    )
    if active_paint is not None:
        return WindowSelector(window_id=active_paint.id)

    raise CUAError(
        "Multiple visible Microsoft Paint windows were found and none is active. "
        "Focus the intended Paint window or specify --window-id."
    )


@app.command()
def screenshot(
    output: str = typer.Option("desktop.png", "--output", "-o"),
    window_id: str | None = typer.Option(None, "--window-id", help="Capture this window handle."),
    process_name: str | None = typer.Option(None, "--process-name", help="Bind to an exact process name, e.g. mspaint.exe."),
    window_title: str | None = typer.Option(None, "--window-title", help="Bind to a window whose title contains this text."),
):
    selector = _window_selector(window_id, process_name, window_title)
    with Computer(target_window=selector) as computer:
        if selector is None:
            computer.screenshot(output)
        else:
            observation = computer.observe(screenshot_path=output)
            if not observation.screenshot or observation.screenshot.coordinate_space != "window":
                raise CUAError("The backend did not return a target-window screenshot.")
    print(f"[green]Saved screenshot:[/green] {output}")


@app.command()
def windows():
    with Computer(accessibility=False) as computer:
        for window in computer.windows():
            active = " [ACTIVE]" if window.is_active else ""
            minimized = " [MINIMIZED]" if window.minimized else ""
            print(
                f"{window.id}\tPID={window.process_id}\t"
                f"{window.process_name or '?'}\t{window.title}{active}{minimized}"
            )


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
    backend: str = typer.Option(
        "native", "--backend", help="Execution backend: native (default) or cua (experimental)."
    ),
    window_id: str | None = typer.Option(None, "--window-id", help="Target a specific ID shown by qwencoder-cua windows."),
    process_name: str | None = typer.Option(None, "--process-name", help="Target an exact process name, e.g. mspaint.exe."),
    window_title: str | None = typer.Option(None, "--window-title", help="Target a window whose title contains this text."),
):
    """Run an observe/plan/act/verify loop, optionally pinned to one application window."""
    if backend not in {"native", "cua"}:
        raise typer.BadParameter("backend must be 'native' or 'cua'.")

    planner = OllamaTaskPlanner(model=model)
    selector = _window_selector(window_id, process_name, window_title)
    driver = None
    if backend == "cua":
        try:
            from qwencoder_cua.drivers.cua.backend import CuaDriverBackend
            driver = CuaDriverBackend()
        except ImportError as exc:
            raise typer.BadParameter(
                'The Cua Driver backend requires pip install -e ".[windows,cua]".'
            ) from exc
        print(
            "[yellow]Experimental backend:[/yellow] Cua Driver owns window capture, "
            "UI Automation and native input."
        )
    try:
        with Computer(driver=driver, target_window=selector) as computer:
            if selector is None:
                automatic_selector = _auto_paint_window_selector(
                    goal, computer.windows(), computer.active_window()
                )
                if automatic_selector is not None:
                    selected = computer.bind_target_window(automatic_selector)
                    print(
                        f"[cyan]Automatically targeting Microsoft Paint:[/cyan] "
                        f"{selected.title} (PID {selected.process_id})"
                    )
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
