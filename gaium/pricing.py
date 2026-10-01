from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None
    cache_write_5m_per_mtok: float | None = None
    cache_write_1h_per_mtok: float | None = None
    total_only_per_mtok: float | None = None


MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-opus-4-8": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-opus-4-7": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-opus-4-6": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-opus-4-5": ModelPricing(5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-sonnet-5": ModelPricing(3.0, 15.0, 0.30, 3.75, 6.0),
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0, 0.30, 3.75, 6.0),
    "claude-sonnet-4-5": ModelPricing(3.0, 15.0, 0.30, 3.75, 6.0),
    "claude-haiku-4-5": ModelPricing(1.0, 5.0, 0.10, 1.25, 2.0),
    "gpt-5.4": ModelPricing(2.50, 15.0, 0.25, total_only_per_mtok=2.50),
    "gpt-5.5": ModelPricing(5.0, 30.0, 0.50, total_only_per_mtok=5.0),
    "gpt-5.6-sol": ModelPricing(4.0, 20.0, 0.40, total_only_per_mtok=4.0),
    "gpt-5.6-luna": ModelPricing(0.20, 1.20, total_only_per_mtok=0.20),
    "gpt-6-astra": ModelPricing(5.0, 25.0, 0.50, 6.25, total_only_per_mtok=5.0),
    "gpt-6.1-sol": ModelPricing(1.0, 5.0, 0.05, 1.25, total_only_per_mtok=1.0),
    "gpt-6-luna": ModelPricing(0.05, 0.25, 0.005, 0.0625, total_only_per_mtok=0.05),
}


def estimate_cost_usd(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    cache_creation_5m_input_tokens: int = 0,
    cache_creation_1h_input_tokens: int = 0,
    total_tokens: int = 0,
) -> tuple[float, bool, str | None]:
    pricing = find_pricing(model)
    if pricing is None:
        return 0.0, False, "missing pricing"

    cost = 0.0
    estimated = False
    note = None

    cost += price_tokens(input_tokens, pricing.input_per_mtok)
    cost += price_tokens(output_tokens, pricing.output_per_mtok)

    if cache_read_input_tokens:
        cost += price_tokens(cache_read_input_tokens, pricing.cached_input_per_mtok or pricing.input_per_mtok * 0.1)

    split_cache_creation = cache_creation_5m_input_tokens + cache_creation_1h_input_tokens
    if split_cache_creation:
        cost += price_tokens(
            cache_creation_5m_input_tokens,
            pricing.cache_write_5m_per_mtok or pricing.input_per_mtok * 1.25,
        )
        cost += price_tokens(
            cache_creation_1h_input_tokens,
            pricing.cache_write_1h_per_mtok or pricing.input_per_mtok * 2,
        )
    elif cache_creation_input_tokens:
        estimated = True
        note = "cache write ttl unknown"
        cost += price_tokens(
            cache_creation_input_tokens,
            pricing.cache_write_5m_per_mtok or pricing.input_per_mtok * 1.25,
        )

    if cost == 0 and total_tokens and pricing.total_only_per_mtok is not None:
        estimated = True
        note = "total tokens only"
        cost = price_tokens(total_tokens, pricing.total_only_per_mtok)

    return cost, estimated, note


def price_tokens(tokens: int, price_per_mtok: float) -> float:
    return tokens / 1_000_000 * price_per_mtok


def find_pricing(model: str | None) -> ModelPricing | None:
    normalized = normalize_model(model)
    if normalized in MODEL_PRICING:
        return MODEL_PRICING[normalized]

    # Claude transcript model IDs may append a release date. Match only that
    # known date form so an unrelated/newer model such as opus-5-5 does not
    # silently inherit opus-5 pricing.
    for known_model, pricing in MODEL_PRICING.items():
        if not known_model.startswith("claude-") or not normalized.startswith(f"{known_model}-"):
            continue
        suffix = normalized[len(known_model) + 1 :]
        if len(suffix) >= 8 and suffix[:8].isdigit():
            return pricing

    return None


def normalize_model(model: str | None) -> str:
    if not model:
        return ""
    return model.strip().lower().replace("_", "-")
