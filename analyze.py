"""Circuit Diagram Analyzer — CLI entry point.

All analysis logic lives in `core/`. This file is just argument parsing
and terminal rendering with `rich`.

Usage:
    python analyze.py <image_path>
    python analyze.py <image_path> --export csv --output bom.csv
    python analyze.py <image_path> --export json
    python analyze.py <image_path> --key <gemini_api_key>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from server import (
    KEY_FILE,
    OUTPUT_DIR,
    analyze_image,
    export_csv,
    export_json,
    load_api_key,
)

console = Console()


def resolve_api_key(cli_key: str | None) -> str:
    if cli_key:
        return cli_key.strip()
    key = load_api_key()
    if key:
        return key
    console.print("[yellow]No Gemini API key found.[/yellow]")
    console.print("Get one at: https://aistudio.google.com/apikey")
    key = console.input("Paste your API key: ").strip()
    if not key:
        console.print("[red]No key provided. Exiting.[/red]")
        sys.exit(1)
    save = console.input("Save to ~/.circuit-analyzer-key for future use? [y/N]: ").strip().lower()
    if save == "y":
        KEY_FILE.write_text(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
        console.print(f"[green]Saved to {KEY_FILE}[/green]")
    return key


def render_results(data: dict) -> None:
    title = data.get("title", "Circuit")
    description = data.get("description", "")
    summary = data.get("summary", "")
    total = data.get("total_count", 0)

    console.print()
    console.print(Panel.fit(
        Text(title, style="bold cyan"),
        subtitle=description,
        border_style="cyan",
    ))

    breakdown = Table(title="Component Breakdown", header_style="bold magenta", border_style="magenta")
    breakdown.add_column("Category", style="cyan")
    breakdown.add_column("Count", justify="right", style="green")
    components = data.get("components", [])
    for cat in components:
        breakdown.add_row(cat.get("category", "?"), str(len(cat.get("items", []))))
    breakdown.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]")
    console.print(breakdown)

    bom = Table(title="Full Bill of Materials", header_style="bold magenta", border_style="magenta")
    bom.add_column("Category", style="cyan")
    bom.add_column("Label", style="yellow")
    bom.add_column("Value", style="green")
    bom.add_column("Type/Notes", style="white")
    for cat in components:
        cat_name = cat.get("category", "?")
        for item in cat.get("items", []):
            bom.add_row(
                cat_name,
                item.get("label", ""),
                item.get("value", ""),
                item.get("type", ""),
            )
    console.print(bom)

    if summary:
        console.print(Panel(summary, title="Summary", border_style="green"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a circuit diagram image with Gemini.")
    parser.add_argument("image", help="Path to circuit diagram image (PNG/JPG/WEBP)")
    parser.add_argument("--export", choices=["csv", "json"], help="Export results to a file")
    parser.add_argument("--output", help="Output file path (defaults to output/<image>.csv|.json)")
    parser.add_argument("--key", help="Gemini API key (overrides env/file)")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        console.print(f"[red]Image not found: {image_path}[/red]")
        sys.exit(1)

    api_key = resolve_api_key(args.key)

    with console.status("[cyan]Analyzing circuit diagram..."):
        try:
            data = analyze_image(image_path, api_key)
        except Exception as exc:
            console.print(f"[red]Analysis failed: {exc}[/red]")
            sys.exit(1)

    render_results(data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    auto_json = OUTPUT_DIR / image_path.with_suffix(".json").name
    export_json(data, auto_json)
    console.print(f"[green]JSON exported to {auto_json}[/green]")

    if args.export:
        if args.output:
            out_path = Path(args.output)
        else:
            out_path = OUTPUT_DIR / image_path.with_suffix(f".{args.export}").name
        if args.export == "csv":
            export_csv(data, out_path)
            console.print(f"[green]CSV exported to {out_path}[/green]")
        elif out_path != auto_json:
            export_json(data, out_path)
            console.print(f"[green]JSON exported to {out_path}[/green]")


if __name__ == "__main__":
    main()