"""Tests for the `music-dl gui` Typer subcommand.

These tests verify:
  - The command is registered and shows correct help text.
  - `--help` exits cleanly without launching a server.
  - The command invokes `tidal_dl.gui.server.run` with the expected arguments.
"""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tidal_dl.cli import app


runner = CliRunner()


class TestGuiCommandHelp:
    """Help text is accessible and describes the command."""

    def test_gui_help_exits_zero(self):
        result = runner.invoke(app, ["gui", "--help"])
        assert result.exit_code == 0

    def test_gui_help_mentions_port(self):
        result = runner.invoke(app, ["gui", "--help"])
        assert "port" in result.output.lower()

    def test_gui_help_mentions_no_browser(self):
        result = runner.invoke(app, ["gui", "--help"])
        assert "no-browser" in result.output.lower() or "no_browser" in result.output.lower()

    def test_gui_appears_in_root_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "gui" in result.output


class TestGuiCommandInvocation:
    """The command delegates to server.run with the right arguments."""

    def test_default_port_and_browser(self):
        with patch("tidal_dl.gui.server.run") as mock_run:
            result = runner.invoke(app, ["gui"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(port=8765, open_browser=True)

    def test_custom_port(self):
        with patch("tidal_dl.gui.server.run") as mock_run:
            result = runner.invoke(app, ["gui", "--port", "9000"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(port=9000, open_browser=True)

    def test_no_browser_flag(self):
        with patch("tidal_dl.gui.server.run") as mock_run:
            result = runner.invoke(app, ["gui", "--no-browser"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(port=8765, open_browser=False)

    def test_custom_port_and_no_browser(self):
        with patch("tidal_dl.gui.server.run") as mock_run:
            result = runner.invoke(app, ["gui", "--port", "9999", "--no-browser"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(port=9999, open_browser=False)
