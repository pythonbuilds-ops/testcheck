"""
PhoneAgent CLI — Rich interactive terminal interface.

Run with: python main.py
Requires: GROQ_API_KEY environment variable

This entrypoint is intended for the local ADB-based runtime.
For the hosted companion bridge, run server.py instead.
"""

import os
import sys
import signal

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.theme import Theme

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

# ── Console Setup ───────────────────────────────────────────────

theme = Theme({
    "info": "dim cyan",
    "warning": "bold yellow",
    "error": "bold red",
    "success": "bold green",
    "agent": "bold magenta",
    "tool": "bold blue",
    "user": "bold white",
    "status": "dim yellow",
})

console = Console(theme=theme)

BANNER = r"""
[bold magenta]
  ____  _                           _                    _   
 |  _ \| |__   ___  _ __   ___    / \   __ _  ___ _ __ | |_ 
 | |_) | '_ \ / _ \| '_ \ / _ \  / _ \ / _` |/ _ \ '_ \| __|
 |  __/| | | | (_) | | | |  __/ / ___ \ (_| |  __/ | | | |_ 
 |_|   |_| |_|\___/|_| |_|\___| /_/   \_\__, |\___|_| |_|\__|
                                         |___/                
[/bold magenta]
[dim]Autonomous Android Control • Multi-Model AI • Persistent Memory[/dim]
"""

HELP_TEXT = """
[bold]Commands:[/bold]
  [cyan]/help[/cyan]        — Show this help
  [cyan]/device[/cyan]      — Show device info
  [cyan]/memory[/cyan]      — Show memory statistics
  [cyan]/memories[/cyan]    — List all stored memories
  [cyan]/history[/cyan]     — Show recent task history
  [cyan]/screenshot[/cyan]  — Take and analyze a screenshot
  [cyan]/screen[/cyan]      — Show current screen elements
  [cyan]/tools[/cyan]       — List all available tools
  [cyan]/clear[/cyan]       — Clear terminal
  [cyan]/quit[/cyan]        — Exit PhoneAgent

[bold]Tips:[/bold]
  • Just type naturally: "open WhatsApp and send hi to Mom"
  • Say "remember that..." to store information
  • Ask "what do you remember about..." to recall facts
  • Complex multi-step tasks are automatically planned and executed
  • Hosted companion mode runs through python server.py, not this CLI
"""


def display_banner():
    """Show the startup banner."""
    console.print(BANNER)


def display_device_info(agent):
    """Show connected device information."""
    if not agent.is_device_connected():
        console.print("[error]✗ No device connected[/error]")
        console.print("[dim]Connect your phone via USB and enable USB debugging.[/dim]")
        console.print("[dim]For hosted companion mode, run python server.py and connect the Android companion app instead.[/dim]")
        return

    info = agent.get_device_info()
    table = Table(title="📱 Connected Device", border_style="cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    for key, value in info.items():
        label = key.replace("_", " ").title()
        table.add_row(label, str(value))
    console.print(table)


def display_memory_stats(agent):
    """Show memory statistics."""
    stats = agent.get_memory_stats()
    table = Table(title="🧠 Memory Statistics", border_style="magenta")
    table.add_column("Store", style="bold")
    table.add_column("Count")
    table.add_row("Short-term items", str(stats.get("short_term_items", 0)))
    table.add_row("Long-term facts", str(stats.get("total_facts", 0)))
    table.add_row("Task episodes", str(stats.get("total_episodes", 0)))

    by_cat = stats.get("by_category", {})
    if by_cat:
        table.add_row("", "")
        for cat, count in by_cat.items():
            table.add_row(f"  └ {cat}", str(count))

    console.print(table)


def display_memories(agent):
    """List all stored memories."""
    memories = agent.get_all_memories()
    if not memories:
        console.print("[dim]No memories stored yet.[/dim]")
        return

    table = Table(title="📝 Stored Memories", border_style="magenta")
    table.add_column("#", style="dim")
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    table.add_column("Category", style="dim")

    for i, m in enumerate(memories[:50], 1):
        val = m["value"]
        if len(val) > 60:
            val = val[:60] + "..."
        table.add_row(str(i), m["key"], val, m["category"])

    console.print(table)


def display_task_history(agent):
    """Show recent task history."""
    episodes = agent.get_recent_tasks(10)
    if not episodes:
        console.print("[dim]No task history yet.[/dim]")
        return

    table = Table(title="📋 Recent Tasks", border_style="blue")
    table.add_column("Status", width=3)
    table.add_column("Task")
    table.add_column("Steps", style="dim")
    table.add_column("Time", style="dim")

    for ep in episodes:
        status = "[success]✓[/success]" if ep.get("success") else "[error]✗[/error]"
        task = ep["task_description"][:50]
        steps = str(len(ep.get("steps", [])))
        duration = f"{ep.get('duration_seconds', 0):.1f}s"
        table.add_row(status, task, steps, duration)

    console.print(table)


def display_tools(agent):
    """List all available tools."""
    tools = agent.tools.list_tools()
    categories = {}
    for tool in tools:
        categories.setdefault(tool.category, []).append(tool)

    for cat, cat_tools in sorted(categories.items()):
        console.print(f"\n[bold cyan]▸ {cat.title()}[/bold cyan]")
        for tool in cat_tools:
            params = ", ".join(
                f"[dim]{p.name}[/dim]" for p in tool.parameters
            )
            console.print(f"  [tool]{tool.name}[/tool]({params}) — {tool.description[:60]}")


def on_status(msg: str):
    """Callback for agent status updates."""
    console.print(f"  [status]⟳ {msg}[/status]")


def on_tool_call(name: str, args: dict):
    """Callback when a tool is about to be called."""
    args_str = ", ".join(f"{k}={repr(v)[:30]}" for k, v in args.items())
    console.print(f"  [tool]▸ {name}[/tool]({args_str})")


def on_tool_result(name: str, result: dict):
    """Callback when a tool completes."""
    success = result.get("success", False)
    icon = "[success]✓[/success]" if success else "[error]✗[/error]"
    res_text = result.get("result", "")
    if len(res_text) > 120:
        res_text = res_text[:120] + "..."
    console.print(f"  {icon} {res_text}")


def main():
    """Main entry point for the PhoneAgent CLI."""
    display_banner()

    if os.environ.get("DEVICE_MODE", "").strip().lower() == "companion":
        console.print("[warning]DEVICE_MODE=companion is set.[/warning]")
        console.print("[dim]This CLI still uses the local desktop runtime. Use python server.py for hosted companion mode.[/dim]")

    # Check API key
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        console.print("[error]✗ GROQ_API_KEY environment variable not set![/error]")
        console.print("[dim]Set it with: set GROQ_API_KEY=your_key_here[/dim]")
        sys.exit(1)

    # Initialize agent
    console.print("[info]Starting PhoneAgent...[/info]")
    try:
        from phoneagent.agent import PhoneAgent
        agent = PhoneAgent(
            api_key=api_key,
            on_status=on_status,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )
    except Exception as e:
        console.print(f"[error]Failed to initialize: {e}[/error]")
        sys.exit(1)

    # Check device
    if agent.is_device_connected():
        info = agent.get_device_info()
        model = info.get("model", "Unknown")
        android = info.get("android_version", "?")
        battery = info.get("battery_level", "?")
        console.print(f"[success]✓ Connected:[/success] {model} (Android {android}) 🔋 {battery}")
    else:
        console.print("[warning]⚠ No local device connected. Connect via USB + enable USB debugging.[/warning]")
        console.print("[dim]For hosted companion mode, run python server.py and connect the Android companion app.[/dim]")
        console.print("[dim]You can still chat, but phone commands won't work.[/dim]")

    console.print('[dim]Type [bold]/help[/bold] for commands, or just chat naturally.[/dim]\n')

    # Setup prompt session with history
    history_dir = os.path.join(os.path.expanduser("~"), ".phoneagent")
    os.makedirs(history_dir, exist_ok=True)
    history_path = os.path.join(history_dir, "prompt_history.txt")

    session = PromptSession(
        history=FileHistory(history_path),
        auto_suggest=AutoSuggestFromHistory(),
    )

    # Graceful exit
    def signal_handler(sig, frame):
        console.print("\n[dim]Shutting down...[/dim]")
        agent.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # ── Main Loop ───────────────────────────────────────────────

    while True:
        try:
            user_input = session.prompt(
                "\n🤖 You > ",
            ).strip()

            if not user_input:
                continue

            # Handle commands
            cmd = user_input.lower()

            if cmd in ("/quit", "/exit", "/q"):
                console.print("[dim]Goodbye! 👋[/dim]")
                agent.shutdown()
                break

            elif cmd == "/help":
                console.print(Panel(HELP_TEXT, title="PhoneAgent Help", border_style="cyan"))
                continue

            elif cmd == "/device":
                display_device_info(agent)
                continue

            elif cmd == "/memory":
                display_memory_stats(agent)
                continue

            elif cmd == "/memories":
                display_memories(agent)
                continue

            elif cmd == "/history":
                display_task_history(agent)
                continue

            elif cmd == "/screenshot":
                on_status("Taking screenshot...")
                result = agent.execute_direct_tool("take_screenshot")
                if result.get("success"):
                    console.print(Panel(
                        result.get("description", result.get("result", "")),
                        title="📸 Screenshot Analysis",
                        border_style="green",
                    ))
                else:
                    console.print(f"[error]{result.get('result', 'Screenshot failed')}[/error]")
                continue

            elif cmd == "/screen":
                on_status("Reading screen...")
                result = agent.execute_direct_tool("get_screen_info")
                console.print(Panel(
                    result.get("result", "No data"),
                    title="📱 Screen Info",
                    border_style="cyan",
                ))
                continue

            elif cmd == "/tools":
                display_tools(agent)
                continue

            elif cmd == "/clear":
                console.clear()
                display_banner()
                continue

            # Process natural language message
            console.print()
            response = agent.process_message(user_input)
            console.print()
            console.print(Panel(
                Markdown(response),
                title="[agent]PhoneAgent[/agent]",
                border_style="magenta",
                padding=(1, 2),
            ))

        except KeyboardInterrupt:
            console.print("\n[dim]Use /quit to exit[/dim]")
            continue
        except EOFError:
            break
        except Exception as e:
            console.print(f"[error]Error: {e}[/error]")
            continue


if __name__ == "__main__":
    main()
