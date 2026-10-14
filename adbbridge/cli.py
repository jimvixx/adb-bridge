import argparse
from pathlib import Path
from .core import Agent, load_config
def main():
    p = argparse.ArgumentParser(prog="adbbridge"); p.add_argument("--queue", type=Path, required=True); p.add_argument("--config", type=Path, required=True); p.add_argument("--once", action="store_true"); p.add_argument("--interval", type=float, default=.25)
    a = p.parse_args(); agent = Agent(a.queue, load_config(a.config)); agent.once() if a.once else agent.loop(a.interval)
