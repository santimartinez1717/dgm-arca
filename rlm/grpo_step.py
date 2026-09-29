"""One GRPO update step, written by hand. This is the part you must understand, not just run.

``GRPOTrainer`` hides the algorithm behind a ``.train()`` call. Here you reimplement its
core on plain tensors, following the slides step by step:

    Step 2: sample a group of G outputs for the same question   (done by the caller)
    Step 3: advantages   A_i = (r_i - mean(r)) / (std(r) + eps)
    Step 4: policy ratio ρ_{i,t} = π_θ(o_{i,t}) / π_{θ_old}(o_{i,t})
            clipped objective  min(ρ·A, clip(ρ, 1-ε, 1+ε)·A)
            optional KL penalty  D_KL(π_θ || π_ref) ≈ exp(logp_ref - logp) - (logp_ref - logp) - 1
            loss = -( mean over tokens of clipped objective  -  β · KL )

Everything works on *log-probabilities per token*, shaped ``(G, T)``, with a mask that is
1 on completion tokens and 0 on padding. Do not touch the model here: the caller computes
the log-probs; you compute the loss.

Run the tests to check your implementation::

    uv run pytest tests/test_grpo_step.py -v

They are marked as expected failures until you implement the functions.
"""

from __future__ import annotations

import torch


def group_advantages(rewards: torch.Tensor, eps: float = 1e-4, scale: bool = True) -> torch.Tensor:
    """Step 3 of the slides: normalise rewards within the group.

    Args:
        rewards: shape ``(G,)``, one scalar reward per sampled output.
        eps: numerical guard for the standard deviation.
        scale: if False, return ``r_i - mean(r)`` without dividing by the std.

    Returns:
        Advantages with shape ``(G,)``. A positive advantage means "better than the group".
    """
    centered = rewards - rewards.mean()
    if not scale:
        return centered
    # Population std (unbiased=False): with G=8 the Bessel correction would inflate every
    # advantage by sqrt(8/7) for no reason. If all rewards are equal, centered is 0 and eps
    # keeps us from dividing 0 by 0: the group carries no learning signal.
    return centered / (rewards.std(unbiased=False) + eps)


def policy_ratio(logp_new: torch.Tensor, logp_old: torch.Tensor) -> torch.Tensor:
    """ρ_{i,t} = π_θ / π_{θ_old}, computed in log space for numerical stability.

    Both inputs have shape ``(G, T)``. Return a tensor of the same shape.
    """
    # exp(log a - log b) = a / b, without ever forming tiny probabilities in float.
    return torch.exp(logp_new - logp_old)


def clipped_objective(
    ratio: torch.Tensor, advantages: torch.Tensor, epsilon: float = 0.2
) -> torch.Tensor:
    """Per-token GRPO surrogate with clipping (variation 1 in the slides).

    Args:
        ratio: shape ``(G, T)``.
        advantages: shape ``(G,)``; broadcast over the token dimension.
        epsilon: clipping range.

    Returns:
        Per-token objective, shape ``(G, T)``, *before* masking and averaging.
    """
    adv = advantages.unsqueeze(-1)  # (G, 1): the same advantage for every token of output i
    unclipped = ratio * adv
    clipped = torch.clamp(ratio, 1 - epsilon, 1 + epsilon) * adv
    # The minimum makes the objective pessimistic: the policy gets no extra credit for moving
    # further than epsilon in the direction the advantage asks for, but a move in the wrong
    # direction is always penalised in full.
    return torch.minimum(unclipped, clipped)


def kl_penalty(logp_new: torch.Tensor, logp_ref: torch.Tensor) -> torch.Tensor:
    """Per-token estimate of D_KL(π_θ || π_ref) used by DeepSeekMath (variation 2).

    exp(logp_ref - logp_new) - (logp_ref - logp_new) - 1. Always >= 0. Shape ``(G, T)``.
    """
    # The k3 estimator (Schulman): unbiased, and x - log(x) - 1 >= 0 for any ratio x.
    delta = logp_ref - logp_new
    return torch.exp(delta) - delta - 1


def grpo_loss(
    logp_new: torch.Tensor,
    logp_old: torch.Tensor,
    rewards: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 0.2,
    beta: float = 0.0,
    logp_ref: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Put the pieces together and return the scalar loss to minimise.

    Average the per-token objective over the valid tokens of each output (``1/|o_i|`` in the
    formula), then over the group (``1/G``). Subtract β times the masked-mean KL when
    ``beta > 0``. Return ``(-objective, stats)`` where ``stats`` holds at least
    ``mean_advantage``, ``clip_fraction`` (share of tokens where clipping was active) and
    ``kl`` for logging.
    """
    mask = mask.to(logp_new.dtype)
    tokens_per_output = mask.sum(dim=1).clamp(min=1)

    advantages = group_advantages(rewards)
    ratio = policy_ratio(logp_new, logp_old)
    per_token = clipped_objective(ratio, advantages, epsilon)

    kl_value = torch.zeros((), dtype=logp_new.dtype)
    if beta > 0:
        if logp_ref is None:
            raise ValueError("beta > 0 needs the reference log-probs")
        per_token_kl = kl_penalty(logp_new, logp_ref)
        per_token = per_token - beta * per_token_kl
        kl_value = ((per_token_kl * mask).sum(dim=1) / tokens_per_output).mean()

    # 1/|o_i| inside each output, then 1/G over the group, exactly as in the GRPO formula.
    objective = ((per_token * mask).sum(dim=1) / tokens_per_output).mean()

    with torch.no_grad():
        adv = advantages.unsqueeze(-1)
        # Clipping is active where the clipped branch won the minimum and cut the gradient.
        clipped_mask = ((ratio > 1 + epsilon) & (adv > 0)) | ((ratio < 1 - epsilon) & (adv < 0))
        clip_fraction = (clipped_mask.to(mask.dtype) * mask).sum() / mask.sum().clamp(min=1)
    stats = {
        "mean_advantage": float(advantages.mean()),
        "clip_fraction": float(clip_fraction),
        "kl": float(kl_value),
        "objective": float(objective.detach()),
    }
    return -objective, stats
