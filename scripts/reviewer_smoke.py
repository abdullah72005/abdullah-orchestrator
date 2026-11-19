#!/usr/bin/env python3
"""Isolated authenticated Reviewer Read smoke (operator launched).

This tool prepares a disposable Git checkout, an isolated supervisor
config/state/registry, a real supervisor writer boundary, a real verification
record, and the digest-bound review projection.  It then stops.

The operator launches exactly one real Reviewer dispatch with::

    python3 scripts/reviewer_smoke.py launch --root <ROOT>

and inspects the recorded evidence with::

    python3 scripts/reviewer_smoke.py inspect --root <ROOT>

The challenge asks the model to read a named projected hunk and report an
added sentinel line that the prompt itself never reveals.  A missing Read
tool, an unreadable projection, a shell/write escape, or a changed checkout is
recorded as a failure; nothing is silently repaired or retried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ORCHESTRATOR_ROOT / "scripts"
SENTINEL_NAME = "MAGIC_SENTINEL"
SENTINEL_VALUE = 314159
SENTINEL_LINE = f"{SENTINEL_NAME} = {SENTINEL_VALUE}"
MANIFEST_NAME = "smoke-manifest.json"


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _git(project, *args):
    return subprocess.run(["git", *args], cwd=str(project),
                          capture_output=True, text=True, check=True).stdout.strip()


def _load_orchestrator(root):
    """Import the supervisor only after the isolated environment is set."""
    for key in ("ABDULLAH_JOB_ID", "ABDULLAH_RUN_ID", "ABDULLAH_CHECK_TOKEN",
                "ABDULLAH_PARENT_JOB", "ABDULLAH_AGENT_CONTEXT"):
        os.environ.pop(key, None)
    os.environ["ABDULLAH_CONFIG"] = str(Path(root) / "config.json")
    os.environ["ABDULLAH_STATE_DIR"] = str(Path(root) / "state" / "runs")
    os.environ["ABDULLAH_CHECKOUT_REGISTRY"] = str(Path(root) / "registry")
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import orchestrator as orc  # noqa: PLC0415 - intentional post-env import
    return orc


def _command_version(name):
    resolved = shutil.which(name)
    if not resolved:
        return {"available": False, "command": name}
    try:
        proc = subprocess.run([resolved, "--version"], capture_output=True,
                              text=True, timeout=20, check=False)
        return {"available": True, "command": resolved,
                "exit": proc.returncode,
                "version": ((proc.stdout or "") + (proc.stderr or "")).strip()[:200]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": True, "command": resolved,
                "error": exc.__class__.__name__}


def prepare(root, keep=True):
    root = Path(root).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"Refusing to reuse a non-empty root: {root}")
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "reviewer-smoke@invalid")
    _git(repo, "config", "user.name", "Reviewer Smoke")
    (repo / "app.py").write_text(
        "def value():\n"
        "    return 41\n"
        "\n"
        "def label():\n"
        "    return 'probe'\n", encoding="utf-8")
    (repo / "README.md").write_text(
        "# Reviewer read smoke fixture\n\nDisposable checkout.\n",
        encoding="utf-8")
    (repo / "test_app.py").write_text(
        "import unittest\n"
        "\n"
        "import app\n"
        "\n"
        "\n"
        "class AppTests(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual(app.value(), 314159)\n"
        "\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n", encoding="utf-8")
    _git(repo, "add", "app.py", "README.md", "test_app.py")
    _git(repo, "commit", "-q", "-m", "fixture base")

    config = _read_json(SCRIPTS / "config.example.json")
    config["workers"]["reviewer"] = {
        "provider": "opencode-go",
        "model": "opencode-go/deepseek-v4.1-flash",
        "variant": "high",
        "billing": "go",
    }
    config.setdefault("limits", {})["max_stage_seconds"] = 900
    _write_json(root / "config.json", config)

    orc = _load_orchestrator(root)
    goal = (
        "Independent readability probe. A supervisor-generated read-only "
        "review projection exists inside this checkout. Use the Read tool on "
        "the named projected hunk and report the exact added line that defines "
        "an integer sentinel constant. Do not guess or reconstruct it from the "
        "prompt.")
    run_id, folder, state = orc.create_run(
        project=repo, goal=goal, host="codex", skip_doctor=True)
    cfg = orc.config()
    plan = {
        "contract_version": 2, "status": "complete",
        "summary": "Reviewer read smoke fixture plan",
        "invariants": ["The checkout stays unchanged during review"],
        "batches": [{
            "title": "reviewer read probe",
            "goal": "Expose one readable changed hunk",
            "acceptance": ["The added sentinel line is reported verbatim"],
            "checks": [[sys.executable, "-m", "unittest", "-v", "test_app"]],
            "risk": "ordinary",
        }],
        "blocker": "",
    }
    state.update({
        "plan": plan, "plan_version": orc.content_hash(plan),
        "plan_revision": 1, "batch_index": 0, "phase": "review",
        "status": "running",
    })
    orc.save(folder, state)

    job_id = "smoke-writer-" + uuid.uuid4().hex[:8]
    (folder / "jobs" / job_id).mkdir(parents=True)
    boundary = orc.capture_batch_boundary(
        repo, folder, job_id, batch_index=0,
        plan_version=state["plan_version"], previous_job_id=None)
    (repo / "app.py").write_text(
        "def value():\n"
        "    return 41\n"
        "\n"
        f"{SENTINEL_LINE}\n"
        "\n"
        "def label():\n"
        "    return 'probe'\n", encoding="utf-8")
    (repo / "app.py").write_text(
        (repo / "app.py").read_text(encoding="utf-8").replace(
            "return 41", "return 314159"), encoding="utf-8")
    final_snapshot = orc.source_snapshot(repo)
    index = orc.finalize_batch_delta(
        repo, folder, job_id, boundary, final_snapshot=final_snapshot,
        attempt=1)
    if not isinstance(index, dict):
        raise SystemExit("The supervisor writer boundary produced no delta index")
    state.setdefault("batch_deltas", []).append({
        "job_id": job_id, "batch_index": 0, "attempt": 1,
        "head": boundary.get("head"), "index": index,
        "hunks_dir": index.get("hunks_dir"),
        "paths": index.get("paths", []),
        "limitations": index.get("limitations", []),
        "recorded_at": orc.now(),
    })
    orc.save(folder, state)

    verification = orc.run_checks(folder, state, cfg, repo, plan["batches"][0])
    if not verification.get("passed"):
        raise SystemExit("Supervisor verification did not pass: "
                         + json.dumps(verification)[:800])
    package = orc.verification_evidence_package(
        state["verification"], orc.source_snapshot(repo), run_id=run_id,
        plan_version=state.get("plan_version"), run_state=state)
    projection, rejection = orc.prepare_review_projection(
        folder, state, cfg, repo, plan["batches"][0], package)
    if rejection is not None:
        raise SystemExit("Review projection failed: " + str(rejection))
    orc.save(folder, state)

    relative_root = Path(projection["root"]).relative_to(repo)
    hunk = None
    for name in projection["files"]:
        candidate = Path(projection["root"]) / name
        if candidate.suffix != ".patch":
            continue
        if SENTINEL_LINE in candidate.read_text(encoding="utf-8", errors="replace"):
            hunk = name
            break
    if hunk is None:
        raise SystemExit("No projected hunk contains the sentinel line")
    hunk_relative = (relative_root / hunk).as_posix()
    prompt = (
        "You are the independent Reviewer for exactly one read-only probe.\n\n"
        "A supervisor-generated review projection is inside this checkout at:\n"
        f"  {relative_root.as_posix()}/\n\n"
        f"Use the Read tool to open `{hunk_relative}`. Report the exact added "
        f"line that defines the integer sentinel constant in that hunk, verbatim, "
        "including its name, operator and integer value. The prompt deliberately "
        "does not contain that line.\n\n"
        "Rules:\n"
        "- If the Read tool is unavailable or the path is refused, stop and return "
        "status `blocked` with the exact tool error in `summary`.\n"
        "- Do not use shell, edit, glob, grep, web or subagent tools. Read only.\n"
        "- Do not guess from this prompt.\n\n"
        "Return one JSON object with exactly these keys: "
        '{"status": "complete"|"blocked", "summary": string, "findings": [], '
        '"files": [string], "tests": [string], "evidence": [string], '
        '"unknowns": [string], "blocker": string}. '
        "Put the quoted line and the hunk path in `summary`, and also list the "
        "hunk path plus the quoted line in `evidence`. Use `findings: []` for "
        "this read-only probe. If blocked, keep every key but use `status`: "
        '"blocked" and describe the tool error in `summary` and `blocker`.')
    prompt_path = folder / "reviewer-smoke-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    manifest = {
        "version": 1, "root": str(root), "repo": str(repo),
        "run_id": run_id, "run_dir": str(folder),
        "config": str(root / "config.json"),
        "state_dir": str(root / "state" / "runs"),
        "registry": str(root / "registry"),
        "projection_root": str(projection["root"]),
        "projection_relpath": relative_root.as_posix(),
        "hunk_relpath": hunk_relative,
        "hunk_path": str(Path(projection["root"]) / hunk),
        "hunk_sha256": _sha256_file(Path(projection["root"]) / hunk),
        "manifest_path": projection["manifest"],
        "manifest_sha256": projection["manifest_sha256"],
        "projection_sha256": projection["projection_sha256"],
        "binding_sha256": projection["binding_sha256"],
        "verification_path": state["verification"]["path"],
        "verification_sha256": _sha256_file(state["verification"]["path"]),
        "candidate_signature": orc.signature(orc.source_snapshot(repo)),
        "prompt_path": str(prompt_path),
        "prompt_sha256": _sha256_file(prompt_path),
        "route": orc.route_report(state, "reviewer", stage="review"),
        "binaries": {"opencode": _command_version("opencode"),
                     "codex": _command_version("codex")},
        "orchestrator_revision": _git(ORCHESTRATOR_ROOT, "rev-parse", "HEAD"),
        "prepared_at": orc.now(),
    }
    launch = ("cd " + _shell_quote(ORCHESTRATOR_ROOT)
              + " && python3 scripts/reviewer_smoke.py launch --root "
              + _shell_quote(root))
    manifest["launch_command"] = launch
    _write_json(root / MANIFEST_NAME, manifest)
    print(json.dumps({"prepared": True, "root": str(root),
                      "run_id": run_id, "hunk": hunk_relative,
                      "launch_command": launch}, indent=2))
    return manifest


def _shell_quote(value):
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:@,+-]+", text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _tool_events(events_path):
    matches = []
    try:
        lines = Path(events_path).read_text(encoding="utf-8",
                                            errors="replace").splitlines()
    except OSError:
        return matches
    for line in lines:
        if '"read"' not in line and '"tool"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        text = json.dumps(event, sort_keys=True)
        if re.search(r'"tool"\s*:\s*"read"|"name"\s*:\s*"read"|"type"\s*:\s*"read"',
                     text):
            matches.append({"event": event, "line_sha256":
                            hashlib.sha256(text.encode()).hexdigest()})
        if len(matches) >= 20:
            break
    return matches


def launch(root):
    root = Path(root).expanduser().resolve()
    manifest = _read_json(root / MANIFEST_NAME)
    orc = _load_orchestrator(root)
    folder = Path(manifest["run_dir"])
    repo = Path(manifest["repo"])
    state = orc.read_json(folder / "state.json")
    before = orc.signature(orc.source_snapshot(repo))
    if before != manifest["candidate_signature"]:
        raise SystemExit("Checkout changed since preparation; re-run prepare")
    prompt = Path(manifest["prompt_path"]).read_text(encoding="utf-8")
    projection = state.get("review_projection")
    if not isinstance(projection, dict):
        raise SystemExit("Prepared run lost its review projection")
    started = time.time()
    report = None
    error = None
    try:
        report, job = orc.call_model(
            folder, state, orc.config(), "reviewer", "reviewer", prompt, repo,
            dispatch_evidence=projection)
    except BaseException as exc:  # record the exact refusal, never hide it
        error = f"{exc.__class__.__name__}: {exc}"
        job = state.get("active_job") or {}
    elapsed = round(time.time() - started, 2)
    after = orc.signature(orc.source_snapshot(repo))
    job_path = Path(job.get("path") or "")
    events = _tool_events(job_path / "events.log") if job_path else []
    summary = str((report or {}).get("summary") or "")
    found = SENTINEL_LINE in summary
    profile = orc.opencode_profile("reviewer", "v2")
    rules = profile.get("permissions") or []
    effective = {
        "read_hunk": orc.v2_effective_permission(
            rules, "read", manifest["hunk_relpath"]),
        "shell": orc.v2_effective_permission(rules, "shell", "echo harmless"),
        "edit": orc.v2_effective_permission(
            rules, "edit", "reviewer-smoke-write-probe.txt"),
        "external_directory": orc.v2_effective_permission(
            rules, "external_directory", "/tmp"),
    }
    try:
        orc.validate_v2_effective_permissions("reviewer", rules)
        profile_valid = True
        profile_error = None
    except ValueError as exc:
        profile_valid = False
        profile_error = str(exc)
    try:
        installed_profile = orc.probe_opencode_config(repo, "reviewer", "v2")
    except (OSError, ValueError, RuntimeError,
            subprocess.SubprocessError) as exc:
        installed_profile = f"error:{exc.__class__.__name__}"
    evidence = {
        "version": 1, "root": str(root), "run_id": manifest["run_id"],
        "orchestrator_revision": manifest["orchestrator_revision"],
        "route_configured": manifest["route"]["configured"],
        "route_effective": manifest["route"]["effective"],
        "route_source": manifest["route"]["route_source"],
        "route_provider": manifest["route"]["provider"],
        "model": manifest["route"]["model"], "effort": manifest["route"]["effort"],
        "billing": manifest["route"]["billing"],
        "endpoint": (job.get("preflight") or {}).get("observed"),
        "elapsed_seconds": elapsed, "error": error,
        "job": {key: job.get(key) for key in
                ("id", "status", "role", "kind", "returncode", "session_id",
                 "pid", "path", "error")},
        "report": report,
        "challenge": {
            "sentinel_sha256": hashlib.sha256(SENTINEL_LINE.encode()).hexdigest(),
            "answer_found": found,
            "read_tool_events": len(events),
            "read_events_sha256": [item["line_sha256"] for item in events],
            "hunk_relpath": manifest["hunk_relpath"],
        },
        "source": {
            "before": before, "after": after, "unchanged": before == after,
            "hunk_sha256": _sha256_file(manifest["hunk_path"]),
            "manifest_sha256": manifest["manifest_sha256"],
            "projection_sha256": manifest["projection_sha256"],
            "binding_sha256": manifest["binding_sha256"],
            "verification_sha256": manifest["verification_sha256"],
        },
        "permissions": {
            "normalized_profile": effective,
            "profile_valid": profile_valid, "profile_error": profile_error,
            "installed_agent_introspection": installed_profile,
            "note": ("Normalized rule evaluation is separate from endpoint "
                     "evidence. It proves the shipped profile text denies "
                     "shell/edit and allows read; it does not itself prove the "
                     "model runtime enforced it."),
        },
        "environment": manifest["binaries"],
        "recorded_at": orc.now(),
    }
    _write_json(root / "evidence.json", evidence)
    ok = (error is None and found and before == after
          and effective["read_hunk"] == "allow"
          and effective["shell"] != "allow" and effective["edit"] != "allow")
    print(json.dumps({"ok": ok, "answer_found": found,
                      "read_tool_events": len(events),
                      "checkout_unchanged": before == after,
                      "permissions": effective,
                      "evidence": str(root / "evidence.json"),
                      "summary_tail": summary[-800:]}, indent=2))
    return 0 if ok else 1


def preflight(root):
    """Read-only route/profile readiness check; never dispatches a model."""
    root = Path(root).expanduser().resolve()
    manifest = _read_json(root / MANIFEST_NAME)
    orc = _load_orchestrator(root)
    folder = Path(manifest["run_dir"])
    repo = Path(manifest["repo"])
    state = orc.read_json(folder / "state.json")
    route = (state.get("model_routes") or {}).get("reviewer") or {}
    cfg = orc.config()
    result = orc.route_preflight("reviewer", route, cfg, repo, state,
                                 run_dir=folder)
    profile = orc.opencode_profile("reviewer", "v2")
    dialect = orc._opencode_validated_dialect(cfg)
    payload = {
        "ok": bool(result.get("ok")),
        "route": orc.route_report(state, "reviewer", stage="review"),
        "preflight": result,
        "dialect": dialect.get("dialect"),
        "dialect_error": dialect.get("error"),
        "installed_agent_introspection":
            orc.probe_opencode_config(repo, "reviewer", dialect.get("dialect")),
        "effective_permissions": {
            "read": orc.v2_effective_permission(
                profile["permissions"], "read", manifest["hunk_relpath"]),
            "shell": orc.v2_effective_permission(
                profile["permissions"], "shell", "echo harmless"),
            "edit": orc.v2_effective_permission(
                profile["permissions"], "edit", "probe.txt"),
        },
        "launch_command": manifest["launch_command"],
        "note": ("Read-only readiness: route/preflight, installed dialect and "
                 "normalized permissions. No model child and no billable call."),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def inspect(root):
    root = Path(root).expanduser().resolve()
    evidence_path = root / "evidence.json"
    if not evidence_path.is_file():
        print(json.dumps({"ok": False,
                          "reason": "No evidence.json; the real Reviewer dispatch "
                                    "has not been launched.",
                          "launch_command": _read_json(
                              root / MANIFEST_NAME).get("launch_command")},
                         indent=2))
        return 2
    evidence = _read_json(evidence_path)
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["challenge"]["answer_found"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    prep = subs.add_parser("prepare", help="Build the isolated fixture; no model call")
    prep.add_argument("--root", default=str(
        Path("/tmp/opencode") / ("abdullah-reviewer-smoke-" + time.strftime("%Y%m%dT%H%M%S"))))
    sub = subs.add_parser("launch", help="Operator: dispatch exactly one real Reviewer")
    sub.add_argument("--root", required=True)
    ins = subs.add_parser("inspect", help="Read recorded smoke evidence")
    ins.add_argument("--root", required=True)
    pre = subs.add_parser("preflight",
                          help="Read-only route/profile readiness; no model call")
    pre.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.root)
        return 0
    if args.command == "launch":
        return launch(args.root)
    if args.command == "preflight":
        return preflight(args.root)
    return inspect(args.root)


if __name__ == "__main__":
    sys.exit(main())
