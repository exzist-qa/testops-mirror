"""Command-line interface for testops-mirror."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from testops_mirror.connectors.allure_testops import AllureTestOpsConnector
from testops_mirror.exceptions import AuthError, TestopsMirrorError
from testops_mirror.gitstore import GitStore
from testops_mirror.models import TestCase
from testops_mirror.sync import run_sync

app = typer.Typer(
    name="testops-mirror",
    help="Mirror test cases from a TMS into a Git repository.",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


_ProjectId = Annotated[
    str, typer.Option("--project-id", help="TMS project ID.", envvar="TESTOPS_PROJECT_ID")
]
_Endpoint = Annotated[
    str, typer.Option("--endpoint", help="Base URL of the TMS.", envvar="TESTOPS_ENDPOINT")
]
_Token = Annotated[str, typer.Option("--token", help="API token.", envvar="TESTOPS_TOKEN")]
_Repo = Annotated[str, typer.Option("--repo", help="Local git repository path.")]
_SuiteField = Annotated[
    str,
    typer.Option(
        "--suite-field",
        help="Custom field for folder structure.",
        envvar="TESTOPS_SUITE_FIELD",
    ),
]
_DryRun = Annotated[bool, typer.Option("--dry-run", help="Preview changes without writing.")]
_Verbose = Annotated[bool, typer.Option("-v", "--verbose", help="Verbose logging.")]


@app.command()
def sync(
    project_id: _ProjectId,
    endpoint: _Endpoint,
    token: _Token,
    repo: _Repo = "./mirror",
    suite_field: _SuiteField = "Suite",
    dry_run: _DryRun = False,
    verbose: _Verbose = False,
) -> None:
    """Mirror all test cases from a TMS project into a local Git repository."""
    load_dotenv()

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    connector = AllureTestOpsConnector(
        endpoint=endpoint,
        api_token=token,
        suite_field=suite_field,
    )
    store = GitStore(repo)

    fetched: list[TestCase] = []

    def _on_case(case: TestCase) -> None:
        fetched.append(case)
        if len(fetched) % 50 == 0:
            logging.getLogger(__name__).info("Fetched %d cases so far...", len(fetched))

    try:
        if dry_run:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Fetching test cases...", total=None)
                changes, _ = run_sync(
                    connector,
                    store,
                    project_id,
                    dry_run=True,
                    on_case=_on_case,
                )
                progress.update(task, completed=True)

            console.print(f"Found [bold]{len(fetched)}[/bold] test cases")
            console.print()

            for path in changes.added:
                console.print(f"[green]+[/green] {path}")
            for path in changes.updated:
                console.print(f"[yellow]~[/yellow] {path}")
            for path in changes.deleted:
                console.print(f"[red]-[/red] {path}")

            if not changes.empty:
                console.print()
            console.print(
                f"[bold]{len(changes.added)}[/bold] to add, "
                f"[bold]{len(changes.updated)}[/bold] to update, "
                f"[bold]{len(changes.deleted)}[/bold] to delete"
            )

        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Fetching test cases...", total=None)
                changes, sha = run_sync(
                    connector,
                    store,
                    project_id,
                    on_case=_on_case,
                )
                progress.update(
                    task,
                    description=f"Fetched {len(fetched)} test cases",
                    completed=True,
                )

            if sha:
                console.print(f"[green]Committed[/green] {sha[:8]} — {changes.summary()}")
            else:
                console.print("[dim]Nothing to commit[/dim]")

    except AuthError as exc:
        err_console.print(f"[red]Authentication failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    except TestopsMirrorError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(130)
