.PHONY: all venv run test test-api test-only test-sound playtest perf clean

# Pure-Python engine — no SWIG build step needed (see DECISIONS.md).
# `make all` gets you from fresh clone to ready-to-play in one command.
all: venv

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[agent]'

run: venv
	.venv/bin/python battleship.py

# Full QA suite: TUI scenarios + agent-API scenarios + perf bench.
test: venv
	.venv/bin/python -m tests.qa
	.venv/bin/python -m tests.api_qa

# Agent-API only (faster feedback when tweaking agent_api.py).
test-api: venv
	.venv/bin/python -m tests.api_qa

# Run a subset of the QA suite by name pattern.
#   make test-only PAT=placement
test-only: venv
	.venv/bin/python -m tests.qa $(PAT)

test-sound: venv
	.venv/bin/python -m tests.sound_test

# End-to-end pty + Pilot walkthrough — writes SVG snapshots under tests/out/.
playtest: venv
	.venv/bin/python -m tests.playtest

perf: venv
	.venv/bin/python -m tests.perf

clean:
	rm -rf .venv battleship_tui.egg-info tests/out/*.svg
