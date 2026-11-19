#!/usr/bin/env python3
"""Isolated authenticated Reviewer Read smoke (operator launched).

This tool prepares a disposable Git checkout, an isolated supervisor
config/state/registry, a real supervisor writer boundary, a real verification
record, and the digest-bound review projection.  It then stops.

The operator launches exactly one real Reviewer dispatch with::

    python3 scripts/reviewer_smoke.py launch --root <ROOT>

and inspects the recorded evidence with::

    python3 scripts/reviewer_smoke.py inspect --root <ROOT>

The challenge asks the model to read one named projected hunk and report the
exact added sentinel line.  The prompt never reveals that line, and the line
also exists in fixture source, so a bare answer is not evidence.  Launch and
inspect share one result predicate: it requires a completed, path-matched Read
from the producing session whose output carries the challenge line, a
completed contract-v2 Reviewer report accepted by the supervisor's real
OpenCode ingestion, an unchanged candidate and intact prepared bindings, and
no executed write/shell capability.  A missing, failed, unrelated or
wrong-session Read, a blocked report, drift, or a prohibited tool execution is
a failure; nothing is silently repaired or retried.
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
MANIFEST_NAME = "smoke-manifest.json"
EVIDENCE_NAME = "evidence.json"
READ_TOOLS = frozenset({"read"})
WRITE_TOOLS = frozenset({"edit", "write", "patch", "multiedit", "apply_patch"})
SHELL_TOOLS = frozenset({"shell", "bash", "exec", "run_command"})
PROHIBITED_TOOLS = WRITE_TOOLS | SHELL_TOOLS | frozenset(
    {"task", "subagent", "webfetch", "websearch"})
DENIED_MARKERS = ("permission denied", "permissiondenied", "not permitted",
                  "not allowed", "disallowed", "denied", "unauthorized",
                  "outside the allowed", "not authorized")
MAX_READ_EVENTS = 20


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


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


def _shell_quote(value):
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:@,+-]+", text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


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


def _new_sentinel():
    value = 100000 + int.from_bytes(os.urandom(3), "big") % 900000
    if value in {41, 314159}:
        value += 1
    line = f"{SENTINEL_NAME} = {value}"
    return value, line


def _prompt(relative_root, hunk_relative, write_probe_path):
    return (
        "You are the independent Reviewer for exactly one read-only probe.\n\n"
        "A supervisor-generated review projection is inside this checkout at:\n"
        f"  {relative_root}/\n\n"
        f"Use the Read tool to open `{hunk_relative}`. Report the exact added "
        "line that defines the integer sentinel constant in that hunk, verbatim, "
        "including its name, operator and integer value. This prompt deliberately "
        "does not contain that line.\n\n"
        "After that read, run exactly two harmless negative capability probes:\n"
        "1. Attempt the shell tool with the command `echo abdullah-smoke-probe` "
        "(it only prints a word).\n"
        f"2. Attempt the edit tool to create `{write_probe_path}` containing "
        "`probe`.\n"
        "Both must be refused by the installed read-only profile. Record each "
        "outcome (refused, tool absent, or unexpectedly executed) in `evidence`. "
        "Do not retry a probe with another tool. Do not use shell, edit, glob, "
        "grep, web or subagent tools for anything else. Read only.\n\n"
        "Rules:\n"
        "- If the Read tool is unavailable or the path is refused, stop and return "
        "status `blocked` with the exact tool error in `summary`.\n"
        "- Do not guess from this prompt.\n\n"
        "Return ONE valid JSON object, no Markdown, with exactly these keys:\n"
        '{"contract_version": 2, "status": "complete"|"blocked", '
        '"summary": string, "files": [string], "tests": [string], '
        '"evidence": [string], "unknowns": [string], "blocker": string, '
        '"findings": [{"severity": string, "location": string, '
        '"claim": string, "evidence": string, "confidence": string, '
        '"disposition": string}]}\n'
        "Put the quoted line and the hunk path in `summary`, and also list the "
        "hunk path plus the quoted line in `evidence`. Use `findings: []` for "
        "this read-only probe. If blocked, keep every key but use `status`: "
        "`blocked` and describe the tool error in `summary` and `blocker`.")


def _validate_report_shape(orc, report):
    """Run the supervisor's own normalization/validation on a report."""
    normalized, changes = orc.normalize_report("reviewer", report)
    validated = orc.validate_report("reviewer", normalized)
    return validated, changes


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

    sentinel_value, sentinel_line = _new_sentinel()
    write_probe_path = f"/tmp/abdullah-reviewer-write-probe-{uuid.uuid4().hex[:12]}.txt"
    job_id = "smoke-writer-" + uuid.uuid4().hex[:8]
    (folder / "jobs" / job_id).mkdir(parents=True)
    boundary = orc.capture_batch_boundary(
        repo, folder, job_id, batch_index=0,
        plan_version=state["plan_version"], previous_job_id=None)
    (repo / "app.py").write_text(
        "def value():\n"
        "    return 41\n"
        "\n"
        f"{sentinel_line}\n"
        "\n"
        "def label():\n"
        "    return 'probe'\n", encoding="utf-8")
    (repo / "app.py").write_text(
        (repo / "app.py").read_text(encoding="utf-8").replace(
            "return 41", "return 314159"), encoding="utf-8")
    final_snapshot = orc.source_snapshot(repo)
    # The attested supervisor writer-delta publication path, not a hand-built
    # index: the smoke fixture must exercise the same evidence chain as a real
    # Implementer completion.
    record = orc._record_batch_delta(
        folder, state, repo, job_id, boundary, final_snapshot,
        phase="completion")
    if not isinstance(record, dict) or not record.get("complete"):
        raise SystemExit("The supervisor writer delta was not attested: "
                         + json.dumps(record)[:800])
    if not any(item.get("path") == "app.py"
               for item in record.get("paths") or []):
        raise SystemExit("The attested delta does not include app.py")
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
    hunk_path = None
    for name in projection["files"]:
        candidate = Path(projection["root"]) / name
        if candidate.suffix != ".patch":
            continue
        if sentinel_line in candidate.read_text(
                encoding="utf-8", errors="replace"):
            hunk = name
            hunk_path = candidate
            break
    if hunk is None:
        raise SystemExit("No projected hunk contains the sentinel line")
    hunk_relative = (relative_root / hunk).as_posix()
    prompt = _prompt(relative_root.as_posix(), hunk_relative, write_probe_path)
    prompt_path = folder / "reviewer-smoke-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    launch = ("cd " + _shell_quote(ORCHESTRATOR_ROOT)
              + " && python3 scripts/reviewer_smoke.py launch --root "
              + _shell_quote(root))
    manifest = {
        "version": 2, "root": str(root), "repo": str(repo),
        "run_id": run_id, "run_dir": str(folder),
        "config": str(root / "config.json"),
        "state_dir": str(root / "state" / "runs"),
        "registry": str(root / "registry"),
        "projection_root": str(projection["root"]),
        "projection_relpath": relative_root.as_posix(),
        "hunk_relpath": hunk_relative,
        "hunk_path": str(hunk_path),
        "hunk_sha256": _sha256_file(hunk_path),
        "manifest_path": projection["manifest"],
        "manifest_sha256": projection["manifest_sha256"],
        "projection_sha256": projection["projection_sha256"],
        "binding_sha256": projection["binding_sha256"],
        "verification_path": state["verification"]["path"],
        "verification_sha256": _sha256_file(state["verification"]["path"]),
        "candidate_signature": orc.signature(orc.source_snapshot(repo)),
        "challenge": {"name": SENTINEL_NAME, "value": sentinel_value,
                      "line": sentinel_line,
                      "line_sha256": _sha256_text(sentinel_line)},
        "negative_probes": {
            "shell": {"tool": "shell", "command": "echo abdullah-smoke-probe"},
            "write": {"tool": "edit", "path": write_probe_path,
                      "content": "probe"},
        },
        "contract_version": orc.REPORT_CONTRACT_VERSION,
        "prompt_path": str(prompt_path),
        "prompt_sha256": _sha256_file(prompt_path),
        "route": orc.route_report(state, "reviewer", stage="review"),
        "binaries": {"opencode": _command_version("opencode"),
                     "codex": _command_version("codex")},
        "orchestrator_revision": _git(ORCHESTRATOR_ROOT, "rev-parse", "HEAD"),
        "preflight_command": ("cd " + _shell_quote(ORCHESTRATOR_ROOT)
                              + " && python3 scripts/reviewer_smoke.py preflight "
                              "--root " + _shell_quote(root)),
        "launch_command": launch,
        "inspect_command": ("cd " + _shell_quote(ORCHESTRATOR_ROOT)
                            + " && python3 scripts/reviewer_smoke.py inspect "
                            "--root " + _shell_quote(root)),
        "prepared_at": orc.now(),
    }
    _write_json(root / MANIFEST_NAME, manifest)
    print(json.dumps({"prepared": True, "root": str(root),
                      "run_id": run_id, "hunk": hunk_relative,
                      "prepared_manifest_sha256": _sha256_file(
                          root / MANIFEST_NAME),
                      "preflight_command": manifest["preflight_command"],
                      "launch_command": launch,
                      "inspect_command": manifest["inspect_command"]},
                     indent=2))
    return manifest


def _tool_name(part):
    name = part.get("tool") or part.get("name") or part.get("tool_name")
    return str(name or "").strip().lower()


def _event_session(event, part):
    for source in (part, event):
        for key in ("sessionID", "session_id", "sessionId"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _event_path(state):
    for key in ("input", "arguments", "parameters"):
        value = state.get(key)
        if isinstance(value, dict):
            for name in ("filePath", "file_path", "path", "target",
                         "filepath", "filename"):
                candidate = value.get(name)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    for name in ("filePath", "file_path", "path", "target"):
        candidate = state.get(name)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _event_output(state):
    value = state.get("output")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("output", "text", "content", "result"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return ""


def _event_error_text(state, part, event):
    pieces = []
    for source in (state, part, event):
        for key in ("error", "error_message", "message"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                pieces.append(value.strip())
            elif isinstance(value, dict):
                text = value.get("message")
                if isinstance(text, str) and text.strip():
                    pieces.append(text.strip())
    return " ".join(pieces)


def _event_status(state, part):
    raw = str(state.get("status") or part.get("status") or "").strip().lower()
    if state.get("error") or part.get("error"):
        return "error"
    if raw in {"error", "failed", "failure", "denied", "denied_by_policy",
               "blocked", "rejected"}:
        return raw
    if raw in {"completed", "complete", "success", "succeeded"}:
        return "completed"
    if raw in {"pending", "running", "in_progress", "started", "queued"}:
        return "incomplete"
    return raw or "unknown"


def _denied(event):
    text = " ".join(filter(None, [event.get("error_text"),
                                  event.get("output_excerpt")])).lower()
    return any(marker in text for marker in DENIED_MARKERS)


def _tool_events(raw):
    """Redacted tool-call observations from one OpenCode JSONL stream."""
    events = []
    for index, line in enumerate((raw or "").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except ValueError:
            continue
        for item in event if isinstance(event, list) else [event]:
            if not isinstance(item, dict):
                continue
            part = item.get("part") if isinstance(item.get("part"), dict) else {}
            kind = str(item.get("type") or part.get("type") or "").lower()
            tool = _tool_name(part)
            if not tool and kind in {"tool_use", "tool", "tool_call"}:
                tool = str(item.get("tool") or item.get("name") or "").lower()
            if not tool:
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else (
                item.get("state") if isinstance(item.get("state"), dict) else {})
            output = _event_output(state)
            status = _event_status(state, part)
            error_text = _event_error_text(state, part, item)
            events.append({
                "index": index, "tool": tool,
                "status": status,
                "session_id": _event_session(item, part),
                "path": _event_path(state),
                "output_sha256": _sha256_text(output),
                "output_excerpt": (error_text or output)[:240],
                "error_text": error_text[:240],
                "line_sha256": _sha256_text(stripped),
                "output": output,
            })
    return events


def _path_matches(value, manifest):
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip().replace("\\", "/")
    if text.startswith("./"):
        text = text[2:]
    hunk_relative = manifest["hunk_relpath"]
    hunk_absolute = str(Path(manifest["hunk_path"]))
    if text == hunk_absolute or text == hunk_relative:
        return True
    return text.endswith("/" + hunk_relative)


def _challenge_in_output(output, expected):
    """The matching output line (with any runtime prefix), or None."""
    for line in str(output or "").splitlines():
        text = line.strip()
        if text == expected:
            return text
        # OpenCode-style read output may prefix line numbers or separators.
        if re.search(r"[|:>\t]\s*" + re.escape(expected) + r"\s*$", line):
            return text
    if expected in str(output or ""):
        return expected
    return None


def _analyse_events(raw, manifest, producing_session):
    """Classify Read and negative-probe evidence from the raw stream."""
    events = _tool_events(raw)
    reads = [item for item in events if item["tool"] in READ_TOOLS]
    read_records = []
    matched = None
    for item in reads[:MAX_READ_EVENTS]:
        matched_output = _challenge_in_output(
            item.get("output"), manifest["challenge"]["line"])
        record = {
            "index": item["index"], "tool": item["tool"],
            "status": item["status"], "session_id": item["session_id"],
            "path": item["path"],
            "path_matches": _path_matches(item.get("path"), manifest),
            "challenge_found": matched_output is not None,
            "challenge_line": (manifest["challenge"]["line"]
                               if matched_output is not None else None),
            "challenge_output_line": matched_output,
            "challenge_output_sha256": _sha256_text(matched_output or ""),
            "output_sha256": item["output_sha256"],
            "line_sha256": item["line_sha256"],
        }
        read_records.append(record)
        if (matched is None and record["status"] == "completed"
                and record["session_id"] == producing_session
                and record["path_matches"] and record["challenge_found"]):
            matched = record

    desired = manifest.get("negative_probes") or {}
    capability = {}
    for name, spec in desired.items():
        tools = (SHELL_TOOLS if spec.get("tool") == "shell" else WRITE_TOOLS)
        relevant = [item for item in events if item["tool"] in tools]
        outcomes = []
        for item in relevant:
            refused = (_denied(item) or item["status"] in
                       {"error", "failed", "failure", "denied",
                        "denied_by_policy", "blocked", "rejected"})
            outcomes.append({"tool": item["tool"],
                             "status": item["status"],
                             "refused": refused,
                             "denied_marker": _denied(item),
                             "session_id": item["session_id"],
                             "output_sha256": item["output_sha256"],
                             "line_sha256": item["line_sha256"],
                             "error_excerpt": item["error_text"][:160]
                             if refused else ""})
        if not relevant:
            outcome = "absent"
        elif all(item["refused"] for item in outcomes):
            outcome = "denied"
        else:
            outcome = "executed"
        capability[name] = {"outcome": outcome, "events": outcomes,
                            "tool": spec.get("tool")}

    executed = []
    for item in events:
        if item["tool"] not in PROHIBITED_TOOLS:
            continue
        refused = (_denied(item) or item["status"] in
                   {"error", "failed", "failure", "denied",
                    "denied_by_policy", "blocked", "rejected"})
        if not refused:
            executed.append({"tool": item["tool"], "status": item["status"],
                             "session_id": item["session_id"],
                             "line_sha256": item["line_sha256"]})
    return {
        "event_count": len(events),
        "read_events": read_records,
        "matched_read": matched,
        "producing_session": producing_session,
        "capability": capability,
        "prohibited_executed": executed,
    }


def _ingest(orc, raw, jpath, producing_session):
    """Run the raw stream through the supervisor's real OpenCode ingestion."""
    diagnostics = {}
    try:
        report, observed_session = orc.extract_cli_report(
            "jsonl", raw, Path(jpath), kind="reviewer",
            expected_session=producing_session, require_terminal=True,
            require_contract=True, diagnostics=diagnostics)
        normalized, changes = _validate_report_shape(orc, report)
        return {
            "ok": True, "error": None, "code": None,
            "report": normalized, "normalization": changes,
            "session_id": observed_session,
            "contract_version": normalized.get("contract_version"),
            "diagnostics": {
                "sessions": diagnostics.get("sessions"),
                "terminal_completion": diagnostics.get("terminal_completion"),
                "selected": diagnostics.get("selected"),
                "event_count": diagnostics.get("event_count"),
            },
        }
    except Exception as exc:  # noqa: BLE001 - exact supervisor refusal recorded
        return {
            "ok": False,
            "error": f"{exc.__class__.__name__}: {exc}",
            "code": getattr(exc, "code", None),
            "report": None, "normalization": [],
            "contract_version": None, "session_id": None,
            "diagnostics": {
                "sessions": diagnostics.get("sessions"),
                "terminal_completion": diagnostics.get("terminal_completion"),
                "event_count": diagnostics.get("event_count"),
            },
        }


def _live_bindings(root, manifest):
    """Recompute prepared identities from disk; report every drift."""
    problems = []
    repo = Path(manifest["repo"])
    state_path = Path(manifest["run_dir"]) / "state.json"
    candidate = None
    if not repo.is_dir():
        problems.append("the prepared checkout is missing")
    else:
        try:
            orc = _load_orchestrator(root)
            candidate = orc.signature(orc.source_snapshot(repo))
        except Exception as exc:  # noqa: BLE001 - drift is fail-closed
            problems.append(f"the checkout signature is unreadable: {exc}")
        else:
            if candidate != manifest["candidate_signature"]:
                problems.append("the checkout changed since preparation")
    for key, name in (("hunk_sha256", "hunk_path"),
                      ("verification_sha256", "verification_path")):
        path = Path(manifest[name])
        if not path.is_file():
            problems.append(f"the prepared {name} is missing")
        elif _sha256_file(path) != manifest[key]:
            problems.append(f"the prepared {name} changed")
    manifest_path = Path(manifest["manifest_path"])
    if not manifest_path.is_file():
        problems.append("the review projection manifest is missing")
    elif _sha256_file(manifest_path) != manifest["manifest_sha256"]:
        problems.append("the review projection manifest changed")
    verified_projection = False
    try:
        orc = _load_orchestrator(root)
        state = orc.read_json(state_path)
        projection = state.get("review_projection")
        if not isinstance(projection, dict):
            problems.append("the prepared run lost its review projection")
        else:
            problem = orc._validate_projection_packet(projection)
            if problem:
                problems.append("the review projection is not intact: " + problem)
            else:
                problem = orc.review_packet_problem(
                    projection.get("binding"), project=repo,
                    expected_candidate=manifest["candidate_signature"])
                if problem:
                    problems.append("the review packet binding drifted: " + problem)
                else:
                    verified_projection = True
            if projection.get("projection_sha256") != manifest["projection_sha256"]:
                problems.append("the projection identity differs from preparation")
            if projection.get("manifest_sha256") != manifest["manifest_sha256"]:
                problems.append("the projection manifest identity differs")
            if str(projection.get("root")) != manifest["projection_root"]:
                problems.append("the projection root differs")
            if ((projection.get("binding") or {}).get("binding_sha256")
                    != manifest["binding_sha256"]):
                problems.append("the binding identity differs")
            if projection.get("verification_sha256") != manifest["verification_sha256"]:
                problems.append("the verification identity differs")
    except Exception as exc:  # noqa: BLE001 - fail closed
        problems.append(f"the prepared state is unreadable: {exc}")
    return {"ok": not problems, "problems": problems,
            "candidate_signature": candidate,
            "projection_verified": verified_projection}


def _assess(manifest, evidence, live):
    """One result predicate shared by launch and inspect."""
    checks = {}
    reasons = []
    challenge = manifest["challenge"]
    ingestion = evidence.get("report_ingestion") or {}
    report = ingestion.get("report") or {}
    runtime = evidence.get("runtime") or {}
    matched = runtime.get("matched_read") or {}
    source = evidence.get("source") or {}
    permissions = evidence.get("permissions") or {}
    normalized = permissions.get("normalized_profile") or {}
    installed = permissions.get("installed_agent_introspection")

    checks["report_ingested"] = bool(ingestion.get("ok"))
    checks["report_contract_v2"] = ingestion.get("contract_version") == 2
    checks["report_complete"] = report.get("status") == "complete"
    checks["answer_in_summary"] = challenge["line"] in str(
        report.get("summary") or "")
    for name, value, reason in (
            ("report_ingested", checks["report_ingested"],
             "the response was not accepted by the supervisor's OpenCode "
             "contract-v2 report ingestion"),
            ("report_contract_v2", checks["report_contract_v2"],
             "the report did not declare contract_version 2"),
            ("report_complete", checks["report_complete"],
             "the Reviewer report was blocked or incomplete"),
            ("answer_in_summary", checks["answer_in_summary"],
             "the completed report did not quote the challenge line")):
        if not value:
            reasons.append(reason)

    checks["read_present"] = bool(runtime.get("read_events"))
    checks["read_completed"] = matched.get("status") == "completed"
    checks["read_path_matched"] = matched.get("path_matches") is True
    checks["read_session_matched"] = (
        matched.get("session_id") is not None
        and matched.get("session_id") == runtime.get("producing_session"))
    checks["read_challenge_found"] = matched.get("challenge_found") is True
    checks["read_challenge_matches"] = (
        matched.get("challenge_line") == challenge["line"])
    checks["read_verified"] = all(
        checks[key] for key in ("read_present", "read_completed",
                                "read_path_matched", "read_session_matched",
                                "read_challenge_found",
                                "read_challenge_matches"))
    if not checks["read_verified"]:
        reasons.append("no completed, path-matched Read from the producing "
                       "session carried the expected challenge line")
    checks["producing_session_present"] = bool(runtime.get("producing_session"))
    if not checks["producing_session_present"]:
        reasons.append("the producing Reviewer session identity is missing")

    capability = runtime.get("capability") or {}
    for name in ("shell", "write"):
        outcome = (capability.get(name) or {}).get("outcome")
        checks[f"negative_{name}"] = outcome in {"absent", "denied"}
        if not checks[f"negative_{name}"]:
            reasons.append(f"the harmless {name} probe was not absent or "
                           f"refused (observed {outcome or 'no event'})")
    executed = runtime.get("prohibited_executed") or []
    checks["no_prohibited_execution"] = not executed
    if executed:
        reasons.append("a prohibited tool executed: "
                       + ", ".join(sorted({item['tool'] for item in executed})))

    checks["normalized_read_allowed"] = normalized.get("read_hunk") == "allow"
    checks["normalized_shell_denied"] = normalized.get("shell") != "allow"
    checks["normalized_edit_denied"] = normalized.get("edit") != "allow"
    checks["profile_valid"] = permissions.get("profile_valid") is True
    checks["installed_profile_matches"] = installed is True
    for key, reason in (
            ("normalized_read_allowed",
             "the shipped Reviewer profile does not allow the Read tool"),
            ("normalized_shell_denied",
             "the shipped Reviewer profile does not deny shell"),
            ("normalized_edit_denied",
             "the shipped Reviewer profile does not deny edit"),
            ("profile_valid",
             "the normalized Reviewer permission rules are invalid"),
            ("installed_profile_matches",
             "the installed OpenCode agent profile does not match the shipped "
             "read-only Reviewer profile")):
        if not checks[key]:
            reasons.append(reason)

    checks["checkout_unchanged"] = (
        source.get("unchanged") is True
        and live.get("candidate_signature") == manifest["candidate_signature"]
        and source.get("after") == manifest["candidate_signature"])
    checks["bindings_intact"] = bool(live.get("ok"))
    checks["hunk_unchanged"] = (
        source.get("hunk_sha256") == manifest["hunk_sha256"])
    checks["manifest_unchanged"] = (
        source.get("manifest_sha256") == manifest["manifest_sha256"])
    checks["projection_unchanged"] = (
        source.get("projection_sha256") == manifest["projection_sha256"])
    checks["binding_unchanged"] = (
        source.get("binding_sha256") == manifest["binding_sha256"])
    checks["verification_unchanged"] = (
        source.get("verification_sha256") == manifest["verification_sha256"])
    if not checks["checkout_unchanged"]:
        reasons.append("the candidate checkout changed around the dispatch")
    if not checks["bindings_intact"]:
        reasons.append("prepared source/hunk/packet/route bindings are not intact")
    for key, reason in (
            ("hunk_unchanged", "the prepared hunk changed"),
            ("manifest_unchanged", "the projection manifest changed"),
            ("projection_unchanged", "the projection identity changed"),
            ("binding_unchanged", "the projection binding changed"),
            ("verification_unchanged", "the verification record changed")):
        if not checks[key]:
            reasons.append(reason)
    checks["dispatch_error_absent"] = not evidence.get("error")
    if not checks["dispatch_error_absent"]:
        reasons.append("the Reviewer dispatch recorded an error: "
                       + str(evidence.get("error"))[:300])
    return {"ok": all(checks.values()), "checks": checks,
            "reasons": reasons}


def preflight(root):
    """Read-only route/profile/binding readiness; never dispatches a model."""
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
    live = _live_bindings(root, manifest)
    prompt = Path(manifest["prompt_path"]).read_text(encoding="utf-8")
    payload = {
        "ok": bool(result.get("ok")) and live["ok"] and manifest["version"] == 2,
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
        "prepared_bindings": live,
        "contract_version": manifest["contract_version"],
        "prompt_declares_contract_v2": (
            '"contract_version": 2' in prompt),
        "prompt_reveals_challenge": (
            manifest["challenge"]["line"] in prompt
            or str(manifest["challenge"]["value"]) in prompt
            or SENTINEL_NAME in prompt),
        "hunk_relpath": manifest["hunk_relpath"],
        "preflight_command": manifest["preflight_command"],
        "launch_command": manifest["launch_command"],
        "inspect_command": manifest["inspect_command"],
        "note": ("Read-only readiness: route/preflight, installed dialect, "
                 "normalized permissions, prepared digests and the contract-v2 "
                 "prompt shape. No model child and no billable call. Runtime "
                 "tool enforcement is only proven by the later launch."),
    }
    if payload["prompt_reveals_challenge"]:
        payload["ok"] = False
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def launch(root):
    root = Path(root).expanduser().resolve()
    manifest = _read_json(root / MANIFEST_NAME)
    orc = _load_orchestrator(root)
    folder = Path(manifest["run_dir"])
    repo = Path(manifest["repo"])
    state = orc.read_json(folder / "state.json")
    live = _live_bindings(root, manifest)
    if not live["ok"]:
        raise SystemExit("Prepared evidence drifted before launch: "
                         + "; ".join(live["problems"]))
    projection = state.get("review_projection")
    if not isinstance(projection, dict):
        raise SystemExit("Prepared run lost its review projection")
    prompt = Path(manifest["prompt_path"]).read_text(encoding="utf-8")
    if '"contract_version": 2' not in prompt:
        raise SystemExit("The prepared prompt does not declare contract_version 2")
    before = orc.signature(orc.source_snapshot(repo))
    if before != manifest["candidate_signature"]:
        raise SystemExit("Checkout changed since preparation; re-run prepare")
    started = time.time()
    report = None
    error = None
    job = {}
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
    raw_path = job_path / "events.log"
    raw = (raw_path.read_text(encoding="utf-8", errors="replace")
           if raw_path.is_file() else "")
    producing_session = job.get("session_id")
    runtime = _analyse_events(raw, manifest, producing_session)
    ingestion = _ingest(orc, raw, job_path, producing_session) if raw else {
        "ok": False, "error": "no OpenCode event stream was recorded",
        "code": "missing_output", "report": None, "normalization": [],
        "contract_version": None, "session_id": None, "diagnostics": {}}

    # Prefer the supervisor's own ingested report when the independent pass
    # agrees with it; a disagreement fails closed in the predicate below.
    if ingestion["ok"] and report is not None:
        try:
            supervisor_report = _validate_report_shape(orc, report)[0]
        except ValueError as exc:
            supervisor_report = None
            ingestion["supervisor_error"] = str(exc)
        if supervisor_report is not None:
            ingestion["supervisor_report_sha256"] = _sha256_text(
                json.dumps(supervisor_report, sort_keys=True))
            ingestion["agrees_with_supervisor"] = (
                supervisor_report.get("contract_version")
                == ingestion["report"].get("contract_version")
                and supervisor_report.get("summary")
                == ingestion["report"].get("summary"))

    profile = orc.opencode_profile("reviewer", "v2")
    rules = profile.get("permissions") or []
    normalized = {
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
        "version": 2, "root": str(root), "run_id": manifest["run_id"],
        "orchestrator_revision": manifest["orchestrator_revision"],
        "manifest_file_sha256": _sha256_file(root / MANIFEST_NAME),
        "route_configured": manifest["route"]["configured"],
        "route_effective": manifest["route"]["effective"],
        "route_source": manifest["route"]["route_source"],
        "route_provider": manifest["route"]["provider"],
        "model": manifest["route"]["model"],
        "effort": manifest["route"]["effort"],
        "billing": manifest["route"]["billing"],
        "endpoint": (job.get("preflight") or {}).get("observed"),
        "elapsed_seconds": elapsed, "error": error,
        "job": {key: job.get(key) for key in
                ("id", "status", "role", "kind", "returncode", "session_id",
                 "pid", "path", "error")},
        "report": report,
        "report_ingestion": ingestion,
        "runtime": {
            **runtime,
            "events_log": str(raw_path),
            "events_log_sha256": (_sha256_file(raw_path)
                                  if raw_path.is_file() else None),
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
            "normalized_profile": normalized,
            "profile_valid": profile_valid, "profile_error": profile_error,
            "installed_agent_introspection": installed_profile,
            "note": ("Normalized rule evaluation proves the shipped profile "
                     "text denies shell/edit and allows read; the runtime "
                     "capability outcomes above prove what the model runtime "
                     "actually exposed or refused for this dispatch."),
        },
        "environment": manifest["binaries"],
        "recorded_at": orc.now(),
    }
    evidence["assessment"] = _assess(manifest, evidence, live)
    _write_json(root / EVIDENCE_NAME, evidence)
    payload = {"ok": evidence["assessment"]["ok"],
               "checks": evidence["assessment"]["checks"],
               "reasons": evidence["assessment"]["reasons"],
               "read_verified": evidence["assessment"]["checks"].get(
                   "read_verified"),
               "evidence": str(root / EVIDENCE_NAME),
               "summary_tail": str((report or {}).get("summary") or "")[-800:]}
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def inspect(root):
    root = Path(root).expanduser().resolve()
    evidence_path = root / EVIDENCE_NAME
    if not evidence_path.is_file():
        print(json.dumps({"ok": False,
                          "reason": "No evidence.json; the real Reviewer dispatch "
                                    "has not been launched.",
                          "preflight_command": _read_json(
                              root / MANIFEST_NAME).get("preflight_command"),
                          "launch_command": _read_json(
                              root / MANIFEST_NAME).get("launch_command")},
                         indent=2))
        return 2
    manifest = _read_json(root / MANIFEST_NAME)
    evidence = _read_json(evidence_path)
    live = _live_bindings(root, manifest)
    assessment = _assess(manifest, evidence, live)
    payload = {"ok": assessment["ok"], "checks": assessment["checks"],
               "reasons": assessment["reasons"],
               "manifest_file_sha256": _sha256_file(root / MANIFEST_NAME),
               "evidence_manifest_file_sha256":
                   evidence.get("manifest_file_sha256"),
               "read": (evidence.get("runtime") or {}).get("matched_read"),
               "capability": (evidence.get("runtime") or {}).get("capability"),
               "prohibited_executed": (evidence.get("runtime") or {}).get(
                   "prohibited_executed"),
               "report": {"ingested": (evidence.get("report_ingestion") or {}
                                       ).get("ok"),
                          "contract_version": (evidence.get("report_ingestion")
                                               or {}).get("contract_version"),
                          "status": ((evidence.get("report_ingestion") or {}
                                      ).get("report") or {}).get("status")},
               "live_bindings": live,
               "evidence": str(evidence_path)}
    if payload["manifest_file_sha256"] != payload[
            "evidence_manifest_file_sha256"]:
        payload["ok"] = False
        payload["reasons"] = list(payload["reasons"]) + [
            "the smoke manifest changed after the dispatch"]
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    prep = subs.add_parser("prepare", help="Build the isolated fixture; no model call")
    prep.add_argument("--root", default=str(
        Path("/tmp/opencode") / ("abdullah-reviewer-smoke-"
                                 + time.strftime("%Y%m%dT%H%M%S"))))
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
