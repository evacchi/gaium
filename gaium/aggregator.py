from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .pricing import estimate_cost_usd


DEFAULT_STATE_PATH = Path("~/.local/state/ai-agent-usage.json").expanduser()
DEFAULT_CALIBRATION_PATH = Path("~/.config/gaium/calibration.json").expanduser()
DEFAULT_LOCAL_CONFIG_PATH = Path(__file__).resolve().parent.parent / ".gaium.local.json"
CLAUDE_IDENTITY_FIELDS = {
    "accountuuid",
    "claude_code_account_uuid",
    "claude_code_organization_uuid",
    "organizationuuid",
    "owneraccountuuid",
    "ownerorganizationuuid",
}
CLAUDE_SESSION_FIELDS = {
    "sessionid",
    "sessionuuid",
    "bridgesessionid",
    "conversationid",
    "transcriptid",
}
DEFAULT_LOG_ROOTS = {
    "codex": [
        Path("~/.codex/sessions").expanduser(),
        Path("~/.codex/state_5.sqlite").expanduser(),
    ],
    "claude": [
        Path("~/.claude/logs").expanduser(),
        Path("~/.claude/projects").expanduser(),
    ],
}


@dataclass
class UsageSample:
    agent: str
    source: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_5m_input_tokens: int = 0
    cache_creation_1h_input_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    raw_cost_usd: float = 0.0
    cost_calibration_factor: float = 1.0
    cost_estimated: bool = False
    cost_note: str | None = None
    requests: int = 1
    timestamp: datetime | None = None


@dataclass
class AgentAggregate:
    name: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    raw_cost_usd: float = 0.0
    cost_calibration_factor: float = 1.0
    cost_estimated: bool = False
    cost_notes: set[str] = field(default_factory=set)
    requests: int = 0
    models: set[str] = field(default_factory=set)
    active_model: str | None = None
    last_seen: datetime | None = None

    def add(self, sample: UsageSample) -> None:
        self.input_tokens += sample.input_tokens
        self.output_tokens += sample.output_tokens
        self.cache_creation_input_tokens += sample.cache_creation_input_tokens
        self.cache_read_input_tokens += sample.cache_read_input_tokens
        self.total_tokens += sample.total_tokens
        self.cost_usd += sample.cost_usd
        self.raw_cost_usd += sample.raw_cost_usd or sample.cost_usd
        self.cost_estimated = self.cost_estimated or sample.cost_estimated
        if sample.cost_note:
            self.cost_notes.add(sample.cost_note)
        self.requests += sample.requests

        if sample.model:
            self.models.add(sample.model)

        if sample.timestamp is None:
            return

        if self.last_seen is None or sample.timestamp > self.last_seen:
            self.last_seen = sample.timestamp
            if sample.model:
                self.active_model = sample.model


def collect_usage(
    roots: dict[str, list[Path]] | None = None,
    since: datetime | None = None,
    window_label: str | None = None,
    calibration_path: Path | None = DEFAULT_CALIBRATION_PATH,
    excluded_claude_identity_ids: set[str] | None = None,
    excluded_claude_session_ids: set[str] | None = None,
) -> dict[str, Any]:
    roots = roots or DEFAULT_LOG_ROOTS
    if excluded_claude_identity_ids is None:
        excluded_claude_identity_ids = load_excluded_claude_identity_ids()
    if excluded_claude_session_ids is None:
        excluded_claude_session_ids = load_excluded_claude_session_ids()
    samples = list(
        iter_usage_samples(
            roots,
            since=since,
            excluded_claude_identity_ids=excluded_claude_identity_ids,
            excluded_claude_session_ids=excluded_claude_session_ids,
        )
    )

    agents: dict[str, AgentAggregate] = {}
    for sample in samples:
        aggregate = agents.setdefault(sample.agent, AgentAggregate(name=sample.agent))
        aggregate.add(sample)

    calibration = load_calibration(calibration_path)
    apply_calibration(agents, calibration)

    generated_at = datetime.now(UTC)
    agent_rows = [agent_to_json(agent) for agent in sorted(agents.values(), key=lambda row: row.name)]
    totals = {
        "input_tokens": sum(row["input_tokens"] for row in agent_rows),
        "output_tokens": sum(row["output_tokens"] for row in agent_rows),
        "cache_creation_input_tokens": sum(row["cache_creation_input_tokens"] for row in agent_rows),
        "cache_read_input_tokens": sum(row["cache_read_input_tokens"] for row in agent_rows),
        "total_tokens": sum(row["total_tokens"] for row in agent_rows),
        "raw_cost_usd": round(sum(row["raw_cost_usd"] for row in agent_rows), 6),
        "cost_usd": round(sum(row["cost_usd"] for row in agent_rows), 6),
        "cost_normalized": any(row["cost_calibration_factor"] != 1.0 for row in agent_rows),
        "cost_estimated": any(row["cost_estimated"] for row in agent_rows),
        "requests": sum(row["requests"] for row in agent_rows),
    }

    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "window": {
            "label": window_label,
            "since": since.isoformat() if since else None,
            "until": generated_at.isoformat(),
        },
        "totals": totals,
        "agents": agent_rows,
    }


def iter_usage_samples(
    roots: dict[str, list[Path]],
    since: datetime | None = None,
    excluded_claude_identity_ids: set[str] | None = None,
    excluded_claude_session_ids: set[str] | None = None,
) -> Iterable[UsageSample]:
    if excluded_claude_identity_ids is None:
        excluded_claude_identity_ids = load_excluded_claude_identity_ids()
    if excluded_claude_session_ids is None:
        excluded_claude_session_ids = load_excluded_claude_session_ids()

    claude_paths = sorted(
        {
            path
            for root in roots.get("claude", [])
            if root.exists()
            for path in iter_log_files(root)
        }
    )
    if claude_paths:
        yield from iter_claude_usage_samples(
            claude_paths,
            since=since,
            excluded_identity_ids=excluded_claude_identity_ids,
            configured_excluded_session_ids=excluded_claude_session_ids,
        )

    for agent, paths in roots.items():
        if agent == "claude":
            continue
        for root in paths:
            if not root.exists():
                continue

            if agent == "codex" and root.is_file() and root.suffix in {".db", ".sqlite"}:
                yield from iter_codex_sqlite_samples(root, since=since)
                continue

            for path in iter_log_files(root):
                for event in iter_json_events(path):
                    sample = sample_from_event(agent, path, event)
                    if sample is None:
                        continue
                    if since and sample.timestamp and sample.timestamp < since:
                        continue
                    yield sample


def iter_claude_usage_samples(
    paths: list[Path],
    since: datetime | None,
    excluded_identity_ids: set[str],
    configured_excluded_session_ids: set[str],
) -> Iterable[UsageSample]:
    excluded_session_ids = set(configured_excluded_session_ids)
    identity_paths: set[Path] = set()
    sessions_by_path: dict[Path, set[str]] = {}

    # Claude stores account metadata and transcript events in separate files.
    # Read all session identifiers first so an identity match excludes the
    # corresponding transcript and sidecar logs, regardless of file order.
    for path in paths:
        session_ids: set[str] = set()
        for event in iter_json_events(path):
            event_session_ids = claude_session_ids(event)
            session_ids.update(event_session_ids)
            if excluded_identity_ids and contains_claude_identity(event, excluded_identity_ids):
                identity_paths.add(path)
                excluded_session_ids.update(event_session_ids)
        sessions_by_path[path] = session_ids

    for path in paths:
        if path in identity_paths or sessions_by_path[path] & excluded_session_ids:
            continue

        # Claude may emit several JSONL records for one assistant message as
        # its content blocks stream in. Usage is cumulative, so retain only
        # the latest record for each message ID.
        samples_by_message: dict[str, tuple[datetime | None, int, UsageSample]] = {}
        for index, event in enumerate(iter_json_events(path)):
            sample = sample_from_event("claude", path, event)
            if sample is None:
                continue
            if since and sample.timestamp and sample.timestamp < since:
                continue

            message_id = first_string(event, ("message.id",))
            key = f"message:{message_id}" if message_id else f"event:{index}"
            previous = samples_by_message.get(key)
            current_order = (sample.timestamp or datetime.min.replace(tzinfo=UTC), index)
            previous_order = (
                (previous[0] or datetime.min.replace(tzinfo=UTC), previous[1])
                if previous
                else None
            )
            if previous_order is None or current_order >= previous_order:
                samples_by_message[key] = (sample.timestamp, index, sample)

        yield from (entry[2] for entry in samples_by_message.values())


def claude_session_ids(event: dict[str, Any]) -> set[str]:
    return {
        value
        for key, value in walk_json(event)
        if "".join(character for character in key.casefold() if character.isalnum())
        in CLAUDE_SESSION_FIELDS
        and isinstance(value, str)
        and value
    }


def load_excluded_claude_identity_ids(path: Path = DEFAULT_LOCAL_CONFIG_PATH) -> set[str]:
    try:
        parsed = parse_json(path.read_text(encoding="utf-8"))
    except OSError:
        return set()

    if not isinstance(parsed, dict):
        return set()
    values = parsed.get("exclude_claude_identity_ids", [])
    if not isinstance(values, list):
        return set()
    return {value.strip() for value in values if isinstance(value, str) and value.strip()}


def load_excluded_claude_session_ids(path: Path = DEFAULT_LOCAL_CONFIG_PATH) -> set[str]:
    try:
        parsed = parse_json(path.read_text(encoding="utf-8"))
    except OSError:
        return set()

    if not isinstance(parsed, dict):
        return set()
    values = parsed.get("exclude_claude_session_ids", [])
    if not isinstance(values, list):
        return set()
    return {value.strip() for value in values if isinstance(value, str) and value.strip()}


def contains_claude_identity(event: dict[str, Any], identities: set[str]) -> bool:
    for key, value in walk_json(event):
        if key.casefold() in CLAUDE_IDENTITY_FIELDS and isinstance(value, str) and value in identities:
            return True
    return False


def walk_json(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def iter_log_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return

    candidates = []
    for pattern in ("*.jsonl", "*.json", "*.log", "*.txt"):
        candidates.extend(root.rglob(pattern))

    yield from sorted({path for path in candidates if path.is_file()})


def iter_codex_sqlite_samples(path: Path, since: datetime | None = None) -> Iterable[UsageSample]:
    if not path.exists():
        return

    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return

    try:
        if not sqlite_table_exists(connection, "threads"):
            return

        rows = connection.execute(
            """
            select
                id,
                model,
                model_provider,
                tokens_used,
                created_at,
                created_at_ms,
                updated_at,
                updated_at_ms
            from threads
            where tokens_used > 0
            """
        )
        for row in rows:
            thread_id, model, model_provider, tokens_used, created_at, created_at_ms, updated_at, updated_at_ms = row
            timestamp = timestamp_from_epoch(updated_at_ms) or timestamp_from_epoch(updated_at)
            if since and timestamp and timestamp < since:
                continue

            cost_usd, cost_estimated, cost_note = estimate_cost_usd(
                model=model or model_provider,
                input_tokens=0,
                output_tokens=0,
                total_tokens=int(tokens_used or 0),
            )
            yield UsageSample(
                agent="codex",
                source=f"{path}:{thread_id}",
                model=model or model_provider,
                total_tokens=int(tokens_used or 0),
                cost_usd=cost_usd,
                raw_cost_usd=cost_usd,
                cost_estimated=cost_estimated,
                cost_note=cost_note,
                timestamp=timestamp or timestamp_from_epoch(created_at_ms) or timestamp_from_epoch(created_at),
            )
    except sqlite3.Error:
        return
    finally:
        connection.close()


def sqlite_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def iter_json_events(path: Path) -> Iterable[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    raw = raw.strip()
    if not raw:
        return

    if path.suffix == ".json":
        parsed = parse_json(raw)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    yield item
        elif isinstance(parsed, dict):
            yield parsed
        return

    for line in raw.splitlines():
        parsed = parse_json(line.strip())
        if isinstance(parsed, dict):
            yield parsed


def sample_from_event(agent: str, path: Path, event: dict[str, Any]) -> UsageSample | None:
    usage = first_mapping(event, ("usage", "token_usage", "tokens", "message.usage", "response.usage"))
    source = usage if usage else event

    input_tokens = first_int(
        source,
        (
            "input_tokens",
            "prompt_tokens",
            "message.usage.input_tokens",
            "response.usage.input_tokens",
        ),
    )
    output_tokens = first_int(
        source,
        (
            "output_tokens",
            "completion_tokens",
            "message.usage.output_tokens",
            "response.usage.output_tokens",
        ),
    )
    total_tokens = first_int(source, ("total_tokens", "tokens.total", "usage.total_tokens"))
    cache_creation_input_tokens = first_int(source, ("cache_creation_input_tokens",))
    cache_read_input_tokens = first_int(source, ("cache_read_input_tokens",))
    cache_creation = first_mapping(source, ("cache_creation",))
    cache_creation_5m_input_tokens = first_int(cache_creation or {}, ("ephemeral_5m_input_tokens",))
    cache_creation_1h_input_tokens = first_int(cache_creation or {}, ("ephemeral_1h_input_tokens",))

    if cache_creation_input_tokens == 0:
        cache_creation_input_tokens = cache_creation_5m_input_tokens + cache_creation_1h_input_tokens

    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens

    if input_tokens == 0 and output_tokens == 0 and cache_creation_input_tokens == 0 and cache_read_input_tokens == 0 and total_tokens == 0:
        return None

    timestamp = first_datetime(
        event,
        (
            "timestamp",
            "created_at",
            "time",
            "message.created_at",
            "response.created_at",
        ),
    )
    model = first_string(event, ("model", "model_id", "message.model", "response.model"))
    cost_usd = first_float(event, ("cost_usd", "cost", "price_usd", "billing.cost_usd"))
    cost_estimated = False
    cost_note = None
    if cost_usd == 0:
        cost_usd, cost_estimated, cost_note = estimate_cost_usd(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_5m_input_tokens=cache_creation_5m_input_tokens,
            cache_creation_1h_input_tokens=cache_creation_1h_input_tokens,
            total_tokens=total_tokens,
        )

    return UsageSample(
        agent=agent,
        source=str(path),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_5m_input_tokens=cache_creation_5m_input_tokens,
        cache_creation_1h_input_tokens=cache_creation_1h_input_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        raw_cost_usd=cost_usd,
        cost_estimated=cost_estimated,
        cost_note=cost_note,
        timestamp=timestamp,
    )


def write_state(state: dict[str, Any], output: Path = DEFAULT_STATE_PATH) -> Path:
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(output)
    return output


def load_calibration(path: Path | None = DEFAULT_CALIBRATION_PATH) -> dict[str, float]:
    if path is None:
        return {}

    path = path.expanduser()
    if not path.exists():
        return {}

    parsed = parse_json(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return {}

    agents = parsed.get("agents", parsed)
    if not isinstance(agents, dict):
        return {}

    calibration = {}
    for agent, value in agents.items():
        if isinstance(value, dict):
            value = value.get("cost_multiplier", value.get("multiplier"))
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            calibration[str(agent)] = float(value)
    return calibration


def write_calibration(calibration: dict[str, float], path: Path = DEFAULT_CALIBRATION_PATH) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "agents": {
            agent: {"cost_multiplier": multiplier}
            for agent, multiplier in sorted(calibration.items())
        },
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def apply_calibration(agents: dict[str, AgentAggregate], calibration: dict[str, float]) -> None:
    for agent_name, aggregate in agents.items():
        factor = calibration.get(agent_name, 1.0)
        aggregate.cost_calibration_factor = factor
        aggregate.cost_usd = aggregate.raw_cost_usd * factor
        if factor != 1.0:
            aggregate.cost_estimated = True
            aggregate.cost_notes.add("calibrated")


def agent_to_json(agent: AgentAggregate) -> dict[str, Any]:
    return {
        "name": agent.name,
        "input_tokens": agent.input_tokens,
        "output_tokens": agent.output_tokens,
        "cache_creation_input_tokens": agent.cache_creation_input_tokens,
        "cache_read_input_tokens": agent.cache_read_input_tokens,
        "total_tokens": agent.total_tokens,
        "raw_cost_usd": round(agent.raw_cost_usd, 6),
        "cost_usd": round(agent.cost_usd, 6),
        "cost_calibration_factor": round(agent.cost_calibration_factor, 8),
        "cost_estimated": agent.cost_estimated,
        "cost_notes": sorted(agent.cost_notes),
        "requests": agent.requests,
        "models": sorted(agent.models),
        "active_model": agent.active_model,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None,
        "limits": {},
    }


def parse_window(value: str | None) -> tuple[datetime | None, str]:
    label = value or "all"
    if value is None or value == "all":
        return None, label

    if value == "month":
        now = datetime.now().astimezone()
        month_start = datetime(now.year, now.month, 1).astimezone()
        return month_start.astimezone(UTC), label

    amount = int(value[:-1])
    unit = value[-1]
    now = datetime.now(UTC)
    if unit == "h":
        return now - timedelta(hours=amount), label
    if unit == "d":
        return now - timedelta(days=amount), label
    raise ValueError("window must be month, all, or use h/d suffix, for example 24h or 7d")


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def first_mapping(source: dict[str, Any], keys: Iterable[str]) -> dict[str, Any] | None:
    for key in keys:
        value = dig(source, key)
        if isinstance(value, dict):
            return value
    return None


def first_int(source: dict[str, Any], keys: Iterable[str]) -> int:
    for key in keys:
        value = dig(source, key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def first_float(source: dict[str, Any], keys: Iterable[str]) -> float:
    for key in keys:
        value = dig(source, key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def first_string(source: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = dig(source, key)
        if isinstance(value, str) and value:
            return value
    return None


def first_datetime(source: dict[str, Any], keys: Iterable[str]) -> datetime | None:
    for key in keys:
        value = dig(source, key)
        parsed = parse_datetime(value)
        if parsed:
            return parsed
    return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None

    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def timestamp_from_epoch(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            return parse_datetime(value)

    if not isinstance(value, (int, float)):
        return None

    seconds = float(value)
    if seconds > 10_000_000_000:
        seconds = seconds / 1000

    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def dig(source: dict[str, Any], key: str) -> Any:
    value: Any = source
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value
