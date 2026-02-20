from __future__ import annotations

import argparse
import os
from pathlib import Path

from .core.config import InstallerManifest
from .core.runner import InstallFailure, InstallerEngine


def _default_manifest() -> Path:
    here = Path(__file__).resolve().parent.parent
    return here / "docs" / "installer-manifest.yaml"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pillowfort installer")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["install", "repair", "status", "clean"],
        default="install",
        help="Operation to run",
    )
    parser.add_argument("--manifest", default=str(_default_manifest()), help="Manifest path")
    parser.add_argument("--workspace", default=None, help="Install workspace root")
    parser.add_argument("--dry-run", action="store_true", help="Plan-only run")
    parser.add_argument("--strict-source", action="store_true", help="Fail on source-of-truth mismatches")
    parser.add_argument("--allow-copy-fallback", action="store_true", help="Allow non-canonical copied adapters")
    parser.add_argument("--skip-models", action="store_true", help="Skip model sync")
    return parser


def _build_engine(args: argparse.Namespace) -> InstallerEngine:
    manifest = InstallerManifest.from_path(args.manifest)
    workspace = Path(os.path.expanduser(args.workspace or str(manifest.workspace))).resolve()
    strict = args.strict_source or os.getenv("BUSY38_CANONICAL_ENFORCE", "0") == "1"
    fallback = args.allow_copy_fallback or os.getenv("BUSY38_CANONICAL_FALLBACK_ALLOWED", "0") == "1"
    if not args.allow_copy_fallback and not args.strict_source:
        fallback = fallback or manifest.source_of_truth.allow_copy_fallback

    return InstallerEngine(
        manifest=manifest,
        workspace=workspace,
        dry_run=args.dry_run,
        strict_source=strict,
        fallback_allowed=fallback,
        state_path=workspace,
    )


def _cmd_install(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    engine.run(include_models=not args.skip_models)
    print(f"Install completed. state={engine.state.file_path}")
    return 0


def _cmd_repair(args: argparse.Namespace) -> int:
    # Currently same behavior as install; kept for interface symmetry.
    return _cmd_install(args)


def _cmd_status(args: argparse.Namespace) -> int:
    manifest = InstallerManifest.from_path(args.manifest)
    workspace = Path(os.path.expanduser(args.workspace or str(manifest.workspace))).resolve()
    state_file = workspace / "install-state.json"
    if not state_file.exists():
        print(f"No install state found: {state_file}")
        return 1
    print(state_file.read_text(encoding="utf-8"))
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    manifest = InstallerManifest.from_path(args.manifest)
    workspace = Path(os.path.expanduser(args.workspace or str(manifest.workspace))).resolve()
    removed = []
    for name in ("install-state.json", "installer-report.md", "installer-audit.log"):
        p = workspace / name
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if removed:
        print("Removed:\n" + "\n".join(removed))
    else:
        print("Nothing to clean.")
    return 0


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()

    if args.command == "status":
        return _cmd_status(args)
    if args.command == "clean":
        return _cmd_clean(args)
    if args.command == "repair":
        return _cmd_repair(args)
    if args.command == "install":
        return _cmd_install(args)
    return _cmd_install(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallFailure as exc:
        print(f"Install failed: {exc}")
        raise SystemExit(1)
