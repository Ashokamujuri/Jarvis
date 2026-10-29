import argparse
import sys

from jarvis.app import Jarvis


def main():
    """Initialize and start Jarvis in GUI (default) or CLI mode."""
    parser = argparse.ArgumentParser(description="Jarvis - Personal AI Assistant")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch Jarvis with the desktop GUI interface (default)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Launch Jarvis in CLI terminal mode without GUI",
    )
    args = parser.parse_args()

    # Default to GUI mode unless --cli is explicitly requested
    if args.cli:
        try:
            assistant = Jarvis()
            assistant.start()
        except KeyboardInterrupt:
            print("\nInterrupted. Goodbye!")
    else:
        try:
            from jarvis.gui import launch_gui
            print("Launching Jarvis Desktop GUI with Video Interface...")
            launch_gui()
        except KeyboardInterrupt:
            print("\nGUI closed. Goodbye!")


if __name__ == "__main__":
    main()
