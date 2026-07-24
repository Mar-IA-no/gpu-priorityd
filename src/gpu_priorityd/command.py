from __future__ import annotations

import subprocess
from collections.abc import Sequence

from .errors import GPUPriorityError


def run_command(
    args: Sequence[str],
    *,
    timeout: float = 20,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GPUPriorityError(f"cannot execute {args[0]}: {type(exc).__name__}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise GPUPriorityError(f"{' '.join(args)}: {detail}")
    return result

