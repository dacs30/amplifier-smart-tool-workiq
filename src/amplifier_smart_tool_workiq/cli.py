#!/usr/bin/env python3
"""CLI adapter for the Amplifier Smart Tool for Work IQ."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amplifier_smart_tool_workiq.client import WorkIqMcpClient  # noqa: E402
from amplifier_smart_tool_workiq.command import run_workiq  # noqa: E402
from amplifier_smart_tool_workiq.data_plans import DataPlan  # noqa: E402
from amplifier_smart_tool_workiq.errors import WorkIqError, sanitize  # noqa: E402
from amplifier_smart_tool_workiq.profiles import (  # noqa: E402
    WorkflowProfile,
    WorkflowStore,
    parse_input_values,
)
from amplifier_smart_tool_workiq.workflows import WorkIqService  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _emit_error(
            WorkIqError(
                "bad_invocation",
                message,
                "Run 'workiq-smart-tool --help' for usage.",
            ),
            exit_code=2,
        )
        raise SystemExit(2)


def _emit(document: dict[str, Any]) -> None:
    json.dump(document, sys.stdout, ensure_ascii=True, sort_keys=True)
    sys.stdout.write("\n")


def _emit_error(error: WorkIqError, *, exit_code: int = 1) -> int:
    _emit({"error": error.as_dict()})
    return exit_code


def _success(capability: str, kind: str, result: Any) -> int:
    _emit({"capability": capability, "kind": kind, "result": result})
    return 0


def _manifest(_: argparse.Namespace) -> int:
    content = Path(__file__).with_name("SMART_TOOL.md").read_text(encoding="utf-8")
    return _success("manifest", "deterministic", {"content": content})


def _doctor(_: argparse.Namespace) -> int:
    workiq_path = shutil.which("workiq")
    npx_path = shutil.which("npx")
    checks = {
        "python": {
            "ok": sys.version_info >= (3, 11),
            "version": ".".join(map(str, sys.version_info[:3])),
        },
        "node": {"ok": shutil.which("node") is not None},
        "npx": {"ok": npx_path is not None},
        "workiq": {"ok": workiq_path is not None},
    }
    if workiq_path:
        checks["workiq"]["launcher"] = workiq_path
    elif npx_path:
        checks["workiq"]["launcher"] = "npx fallback"
        checks["workiq"]["note"] = (
            "The npx fallback works, but a global Work IQ installation reduces "
            "CLI startup latency. Install it with "
            "'npm install -g @microsoft/workiq'."
        )
    ok = checks["python"]["ok"] and (
        checks["workiq"]["ok"] or checks["npx"]["ok"]
    )
    return _success("doctor", "deterministic", {"ok": ok, "checks": checks})


def _authenticate(args: argparse.Namespace) -> int:
    command = ["auth", "login"]
    if args.account:
        command.extend(["--account", args.account])
    completed = run_workiq(command, timeout=args.timeout, interactive=True)
    if completed.returncode != 0:
        raise WorkIqError(
            "authentication_failed",
            f"Work IQ authentication exited with code {completed.returncode}.",
            "Review the interactive sign-in output and tenant admin consent.",
        )
    return _success(
        "authenticate",
        "setup",
        {
            "authenticated": True,
            "account": args.account,
            "message": "Work IQ completed its authentication flow.",
        },
    )


def _accept_eula(args: argparse.Namespace) -> int:
    if not args.yes:
        raise WorkIqError(
            "confirmation_required",
            "The Work IQ EULA was not accepted.",
            "Review https://github.com/microsoft/work-iq, then rerun "
            "'workiq-smart-tool accept-eula --yes' to accept it.",
        )
    command = ["accept-eula"]
    if args.account:
        command.extend(["--account", args.account])
    completed = run_workiq(command, timeout=args.timeout)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WorkIqError(
            "eula_acceptance_failed",
            sanitize(detail)
            or f"Work IQ exited with code {completed.returncode}.",
            "Review the Work IQ client output and retry.",
        )
    return _success(
        "accept-eula",
        "setup",
        {
            "accepted": True,
            "message": "The official Work IQ client recorded EULA acceptance.",
        },
    )


def _with_service(
    args: argparse.Namespace,
    operation: Any,
) -> Any:
    with WorkIqMcpClient(account=args.account, timeout=args.timeout) as client:
        return operation(WorkIqService(client))


def _agents(args: argparse.Namespace) -> int:
    result = _with_service(args, lambda service: service.list_agents())
    return _success("agents", "model-backed", result)


def _discover(args: argparse.Namespace) -> int:
    result = _with_service(
        args,
        lambda service: service.discover_paths(args.query),
    )
    return _success("discover", "service-backed", result)


def _schema(args: argparse.Namespace) -> int:
    result = _with_service(
        args,
        lambda service: service.get_schema(
            args.path,
            schema_format=args.format,
            agent_id=args.agent_id,
        ),
    )
    return _success("schema", "service-backed", result)


def _ask(args: argparse.Namespace) -> int:
    result = _with_service(
        args,
        lambda service: service.ask(
            args.question,
            agent_id=args.agent_id,
            time_zone=args.time_zone,
            conversation_id=args.conversation_id,
            file_urls=args.file_url,
        ),
    )
    return _success("ask", "model-backed", result)


def _fetch(args: argparse.Namespace) -> int:
    result = _with_service(args, lambda service: service.fetch(args.path))
    return _success("fetch", "model-backed", result)


def _daily_briefing(args: argparse.Namespace) -> int:
    result = _with_service(
        args,
        lambda service: service.daily_briefing(
            briefing_date=date.fromisoformat(args.date),
            time_zone=args.time_zone,
            mode=args.mode,
        ),
    )
    kind = "service-backed" if args.mode == "fast" else "model-backed"
    return _success("daily-briefing", kind, result)


def _meeting_prep(args: argparse.Namespace) -> int:
    meeting_date = date.fromisoformat(args.date) if args.date else None
    result = _with_service(
        args,
        lambda service: service.meeting_prep(
            meeting=args.meeting,
            meeting_date=meeting_date,
            time_zone=args.time_zone,
        ),
    )
    return _success("meeting-prep", "model-backed", result)


def _workflow_validate(args: argparse.Namespace) -> int:
    profile = WorkflowProfile.read(Path(args.file))
    return _success("workflow validate", "deterministic", profile.to_dict())


def _workflow_create(args: argparse.Namespace) -> int:
    if not args.confirmed:
        raise WorkIqError(
            "confirmation_required",
            "Creating a persistent workflow requires explicit confirmation.",
            "Review the profile, then rerun with --confirmed.",
        )
    profile = WorkflowProfile.read(Path(args.file))
    path = WorkflowStore().create(profile, replace=args.replace)
    return _success(
        "workflow create",
        "deterministic",
        {"profile": profile.to_dict(), "path": str(path)},
    )


def _workflow_list(_: argparse.Namespace) -> int:
    profiles = WorkflowStore().list()
    result = [
        {
            "name": profile.name,
            "description": profile.description,
            "inputs": list(profile.inputs),
        }
        for profile in profiles
    ]
    return _success("workflow list", "deterministic", {"workflows": result})


def _workflow_show(args: argparse.Namespace) -> int:
    profile = WorkflowStore().get(args.name)
    return _success("workflow show", "deterministic", profile.to_dict())


def _workflow_delete(args: argparse.Namespace) -> int:
    if not args.confirmed:
        raise WorkIqError(
            "confirmation_required",
            f"Deleting workflow '{args.name}' requires explicit confirmation.",
            "Review the target, then rerun with --confirmed.",
        )
    WorkflowStore().delete(args.name)
    return _success(
        "workflow delete",
        "deterministic",
        {"deleted": args.name},
    )


def _workflow_run(args: argparse.Namespace) -> int:
    profile = WorkflowStore().get(args.name)
    values = parse_input_values(args.input)
    question = profile.render(values)
    result = _with_service(
        args,
        lambda service: service.ask(
            question,
            agent_id=args.agent_id,
            time_zone=args.time_zone,
        ),
    )
    return _success(
        "workflow run",
        "model-backed",
        {"workflow": profile.name, "response": result},
    )


def _query_validate(args: argparse.Namespace) -> int:
    plan = DataPlan.read(Path(args.file))
    return _success("query validate", "deterministic", plan.to_dict())


def _query_run(args: argparse.Namespace) -> int:
    plan = DataPlan.read(Path(args.file))
    started = time.perf_counter()
    result = _with_service(
        args,
        lambda service: service.fetch(plan.paths()),
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return _success(
        "query run",
        "service-backed",
        {
            "plan": plan.to_dict(),
            "data": result,
            "timings": {"totalMs": elapsed_ms},
        },
    )


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account",
        help="Cached Microsoft 365 account email to pass to Work IQ.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="Maximum seconds to wait for Work IQ (default: 120).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="workiq-smart-tool",
        description=(
            "Safe Microsoft 365 workflows over the official Work IQ MCP server."
        ),
        epilog=(
            "Capabilities:\n"
            "  doctor          [deterministic] Check local prerequisites.\n"
            "  manifest        [deterministic] Return selection metadata.\n"
            "  accept-eula     [setup] Accept the Work IQ EULA.\n"
            "  authenticate    [setup] Start Microsoft 365 sign-in.\n"
            "  agents          [model-backed] List available agents.\n"
            "  discover        [service-backed] Discover Microsoft 365 paths.\n"
            "  schema          [service-backed] Inspect a fetch schema.\n"
            "  ask             [model-backed] Ask a read-only question.\n"
            "  fetch           [model-backed] Fetch bounded entity paths.\n"
            "  daily-briefing  [model-backed] Prepare a daily briefing.\n"
            "  meeting-prep    [model-backed] Prepare for a meeting.\n"
            "  query           Validate and run read-only data plans.\n"
            "  workflow        Create and run domain-specific workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="capability")

    doctor = commands.add_parser(
        "doctor", help="[deterministic] Check local prerequisites."
    )
    doctor.add_argument(
        "--local-only",
        action="store_true",
        help="Do not make network or authentication checks.",
    )
    doctor.set_defaults(handler=_doctor)

    manifest = commands.add_parser(
        "manifest", help="[deterministic] Return the canonical manifest."
    )
    manifest.set_defaults(handler=_manifest)

    accept_eula = commands.add_parser(
        "accept-eula", help="[setup] Explicitly accept the Work IQ EULA."
    )
    _add_runtime_options(accept_eula)
    accept_eula.add_argument(
        "--yes",
        action="store_true",
        help="Confirm that you reviewed and accept Microsoft's Work IQ EULA.",
    )
    accept_eula.set_defaults(handler=_accept_eula)

    authenticate = commands.add_parser(
        "authenticate", help="[setup] Start the Work IQ sign-in flow."
    )
    _add_runtime_options(authenticate)
    authenticate.set_defaults(handler=_authenticate)

    agents = commands.add_parser(
        "agents", help="[model-backed] List available Copilot agents."
    )
    _add_runtime_options(agents)
    agents.set_defaults(handler=_agents)

    discover = commands.add_parser(
        "discover",
        help="[service-backed] Discover Microsoft 365 resource paths.",
    )
    _add_runtime_options(discover)
    discover.add_argument("--query", required=True)
    discover.set_defaults(handler=_discover)

    schema = commands.add_parser(
        "schema",
        help="[service-backed] Inspect a read-only fetch schema.",
    )
    _add_runtime_options(schema)
    schema.add_argument("--path", required=True)
    schema.add_argument(
        "--format",
        choices=("jsonschema", "typescript", "cddl"),
        default="jsonschema",
    )
    schema.add_argument("--agent-id")
    schema.set_defaults(handler=_schema)

    ask = commands.add_parser(
        "ask", help="[model-backed] Ask a read-only workplace question."
    )
    _add_runtime_options(ask)
    ask.add_argument("--question", required=True)
    ask.add_argument("--agent-id")
    ask.add_argument("--time-zone")
    ask.add_argument("--conversation-id")
    ask.add_argument("--file-url", action="append", default=[])
    ask.set_defaults(handler=_ask)

    fetch = commands.add_parser(
        "fetch", help="[model-backed] Fetch bounded Microsoft 365 entities."
    )
    _add_runtime_options(fetch)
    fetch.add_argument("--path", action="append", required=True)
    fetch.set_defaults(handler=_fetch)

    briefing = commands.add_parser(
        "daily-briefing", help="[model-backed] Prepare a daily work briefing."
    )
    _add_runtime_options(briefing)
    briefing.add_argument("--date", default=date.today().isoformat())
    briefing.add_argument("--time-zone")
    briefing.add_argument(
        "--mode",
        choices=("fast", "comprehensive"),
        default="comprehensive",
        help="Use bounded structured reads or full Work IQ synthesis.",
    )
    briefing.set_defaults(handler=_daily_briefing)

    meeting = commands.add_parser(
        "meeting-prep", help="[model-backed] Prepare for a meeting."
    )
    _add_runtime_options(meeting)
    meeting.add_argument("--meeting", required=True)
    meeting.add_argument("--date")
    meeting.add_argument("--time-zone")
    meeting.set_defaults(handler=_meeting_prep)

    workflow = commands.add_parser(
        "workflow", help="Create and run domain-specific Work IQ workflows."
    )
    workflow_commands = workflow.add_subparsers(dest="workflow_capability")

    workflow_validate = workflow_commands.add_parser(
        "validate", help="[deterministic] Validate a workflow profile file."
    )
    workflow_validate.add_argument("--file", required=True)
    workflow_validate.set_defaults(handler=_workflow_validate)

    workflow_create = workflow_commands.add_parser(
        "create", help="[deterministic] Persist a validated workflow profile."
    )
    workflow_create.add_argument("--file", required=True)
    workflow_create.add_argument("--replace", action="store_true")
    workflow_create.add_argument("--confirmed", action="store_true")
    workflow_create.set_defaults(handler=_workflow_create)

    workflow_list = workflow_commands.add_parser(
        "list", help="[deterministic] List persisted workflow profiles."
    )
    workflow_list.set_defaults(handler=_workflow_list)

    workflow_show = workflow_commands.add_parser(
        "show", help="[deterministic] Show one workflow profile."
    )
    workflow_show.add_argument("--name", required=True)
    workflow_show.set_defaults(handler=_workflow_show)

    workflow_delete = workflow_commands.add_parser(
        "delete", help="[deterministic] Delete a workflow profile."
    )
    workflow_delete.add_argument("--name", required=True)
    workflow_delete.add_argument("--confirmed", action="store_true")
    workflow_delete.set_defaults(handler=_workflow_delete)

    workflow_run = workflow_commands.add_parser(
        "run", help="[model-backed] Run a persisted workflow profile."
    )
    _add_runtime_options(workflow_run)
    workflow_run.add_argument("--name", required=True)
    workflow_run.add_argument("--input", action="append", default=[])
    workflow_run.add_argument("--agent-id")
    workflow_run.add_argument("--time-zone")
    workflow_run.set_defaults(handler=_workflow_run)

    query = commands.add_parser(
        "query",
        help="Validate and run bounded read-only data plans.",
    )
    query_commands = query.add_subparsers(dest="query_capability")

    query_validate = query_commands.add_parser(
        "validate",
        help="[deterministic] Validate a data plan file.",
    )
    query_validate.add_argument("--file", required=True)
    query_validate.set_defaults(handler=_query_validate)

    query_run = query_commands.add_parser(
        "run",
        help="[service-backed] Execute a validated data plan.",
    )
    _add_runtime_options(query_run)
    query_run.add_argument("--file", required=True)
    query_run.set_defaults(handler=_query_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if not getattr(args, "capability", None) or (
            args.capability == "workflow"
            and not getattr(args, "workflow_capability", None)
        ) or (
            args.capability == "query"
            and not getattr(args, "query_capability", None)
        ):
            return _emit_error(
                WorkIqError(
                    "no_capability",
                    "No capability was specified.",
                    "Run 'workiq-smart-tool --help' to list capabilities.",
                ),
                exit_code=2,
            )
        return args.handler(args)
    except ValueError as error:
        return _emit_error(
            WorkIqError(
                "invalid_value",
                sanitize(str(error)),
                "Check date values and command arguments, then retry.",
            ),
            exit_code=2,
        )
    except WorkIqError as error:
        return _emit_error(error)
    except (BrokenPipeError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
