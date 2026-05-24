from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from emule_workspace import cli


def test_cli_requires_workspace_root() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["env-check"], env={"EMULE_WORKSPACE_ROOT": ""})

    assert result.exit_code != 0
    assert "EMULE_WORKSPACE_ROOT or --workspace-root is required" in result.output


def test_build_tests_help_exposes_clean_architecture_command() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["build", "tests", "--help"])

    assert result.exit_code == 0
    assert "--test-run-variant" in result.output
    assert "Configured app variant key" in result.output
    assert "worktree" in result.output
    assert "folder" in result.output
    assert "name" in result.output
    assert "--build-output-mode" in result.output


def test_build_app_help_exposes_variant_selection() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["build", "app", "--help"])

    assert result.exit_code == 0
    assert "--variant" in result.output
    assert "Configured app variant key" in result.output
    assert "--clean" in result.output


def test_build_libs_help_exposes_clean_option() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["build", "libs", "--help"])

    assert result.exit_code == 0
    assert "--clean" in result.output


def test_python_test_help_exposes_pytest_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "python", "--help"])

    assert result.exit_code == 0
    assert "--path" in result.output
    assert "--expression" in result.output


def test_test_live_e2e_help_exposes_live_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "live-e2e", "--help"])

    assert result.exit_code == 0
    assert "--suite" in result.output
    assert "--profile" in result.output
    assert "multi-client-p2p" in result.output
    assert "release-expanded" in result.output
    assert "release-expanded-quick" in result.output
    assert "stabilization-stress" in result.output
    assert "stabilization-stress-quick" in result.output
    assert "cpu-heavy-quick" in result.output
    assert "ui-resource-depth" in result.output
    assert "--p2p-bind-interface-name" in result.output
    assert "--live-wire-inputs-file" in result.output
    assert "--arr-download-proof-mode" in result.output
    assert "--pre-run-cleanup" in result.output
    assert "--skip-pre-run-cleanup" in result.output
    assert "--search-ui-search-rounds" in result.output
    assert "--search-ui-download-lifecycle-count" in result.output
    assert "--radarr-movie-root" in result.output
    assert "--sonarr-series-root" in result.output
    assert "--profile-cpu" in result.output
    assert "--profile-cpu-stack" in result.output
    assert "--profile-memory" in result.output
    assert "--profile-resource-interval-seconds" in result.output
    assert "--admin-volume-fixtures" in result.output
    assert "--vhd-size-mb" in result.output
    assert "--mount-root" in result.output
    assert "--keep-admin-fixtures" in result.output
    assert "--rest-cold-start-dump-stress-cpu-profile" in result.output
    assert "--rest-cold-start-dump-stress-cpu-profile-stack" in result.output


def test_test_certification_help_exposes_release_gate_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "certification", "--help"])

    assert result.exit_code == 0
    assert "--profile" in result.output
    assert "overnight" in result.output
    assert "--live-wire-inputs-file" in result.output
    assert "--radarr-movie-root" in result.output
    assert "--sonarr-series-root" in result.output
    assert "--p2p-bind-interface-name" in result.output
    assert "--continue-on-failure" in result.output
    assert "--skip-pre-run-cleanup" in result.output


def test_test_release_campaign_help_exposes_report_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "release-campaign", "--help"])

    assert result.exit_code == 0
    assert "--campaign" in result.output
    assert "--phase" in result.output
    assert "--template" in result.output
    assert "--json" in result.output
    assert "--execute" in result.output
    assert "--include-nonblocking" in result.output
    assert "--continue-on-failure" in result.output
    assert "--dry-run" in result.output
    assert "--skip-pre-run-cleanup" in result.output
    assert "--live-wire-inputs-file" in result.output
    assert "--radarr-movie-root" in result.output
    assert "--sonarr-series-root" in result.output


def test_amutorrent_clean_startup_help_exposes_live_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "amutorrent-clean-startup", "--help"])

    assert result.exit_code == 0
    assert "--live-wire-inputs-file" in result.output
    assert "--rest-webserver-scheme" in result.output
    assert "--p2p-bind-interface-name" in result.output
    assert "--search-observation-timeout-seconds" in result.output


def test_amutorrent_resilience_help_exposes_live_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "amutorrent-resilience", "--help"])

    assert result.exit_code == 0
    assert "--live-wire-inputs-file" in result.output
    assert "--rest-webserver-scheme" in result.output
    assert "--p2p-bind-interface-name" in result.output
    assert "--search-observation-timeout-seconds" in result.output
    assert "--reconnect-timeout-seconds" in result.output


def test_amutorrent_emulebb_ui_help_exposes_live_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["test", "amutorrent-emulebb-ui", "--help"])

    assert result.exit_code == 0
    assert "--live-wire-inputs-file" in result.output
    assert "--rest-webserver-scheme" in result.output
    assert "--p2p-bind-interface-name" in result.output
    assert "--search-observation-timeout-seconds" in result.output
    assert "--keep-artifacts" in result.output


def test_build_all_help_exposes_composed_build_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["build", "all", "--help"])

    assert result.exit_code == 0
    assert "--variant" in result.output
    assert "--test-run-variant" in result.output
    assert "Configured app variant key" in result.output


def test_dep_status_help_is_available() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["dep-status", "--help"])

    assert result.exit_code == 0
    assert "Report dependency" in result.output


def test_workspace_status_help_is_available() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["workspace-status", "--help"])

    assert result.exit_code == 0
    assert "dirty-state" in result.output


def test_validate_help_exposes_product_family_option() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["validate", "--help"])

    assert result.exit_code == 0
    assert "--include-product-family" in result.output


def test_package_release_help_exposes_release_version() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["package-release", "--help"])

    assert result.exit_code == 0
    assert "--release-version" in result.output
    assert "0.7.3" in result.output


def test_package_amutorrent_help_exposes_release_version() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["package-amutorrent", "--help"])

    assert result.exit_code == 0
    assert "--release-version" in result.output
    assert "0.7.3" in result.output


def test_package_amule_help_exposes_release_version() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["package-amule", "--help"])

    assert result.exit_code == 0
    assert "--release-version" in result.output
    assert "3.0.0-emulebb.1" in result.output


def test_package_miniupnpc_help_exposes_release_version() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["package-miniupnpc", "--help"])

    assert result.exit_code == 0
    assert "--release-version" in result.output
    assert "2.2.3-emulebb.1" in result.output


def test_materialize_help_exposes_bootstrap_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["materialize", "--help"])

    assert result.exit_code == 0
    assert "--artifacts-seed-root" in result.output


def test_sync_help_exposes_bootstrap_options() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["sync", "--help"])

    assert result.exit_code == 0
    assert "--workspace-root" in result.output


def test_setup_status_help_is_available() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["status", "--help"])

    assert result.exit_code == 0
    assert "setup-managed" in result.output


def test_dep_updates_help_is_available() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["dep-updates", "--help"])

    assert result.exit_code == 0
    assert "third-party" in result.output


def test_compare_help_is_available() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["compare", "--help"])

    assert result.exit_code == 0
    assert "WinMerge" in result.output


def test_sync_rejects_workspace_root_outside_current_build_clone(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli.main, ["sync", "--workspace-root", str(tmp_path)])

    assert result.exit_code != 0
    assert "repos\\emulebb-build" in result.output
