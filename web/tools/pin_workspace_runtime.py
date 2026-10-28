"""Record installed runtime versions without network, dotenv or application imports.

Not a cross-platform lock solver, hash lock, Linux install proof or vulnerability scan.
Uvicorn minimal server is used; optional standard/watch/reload packages are excluded.
"""

from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    pending = [
        "alembic",
        "email-validator",
        "fastapi",
        "httpx",
        "psycopg[binary]",
        "pydantic-settings",
        "PyJWT",
        "pwdlib[argon2]",
        "sqlalchemy",
        "uvicorn",
        "tzdata",
    ]
    seen = set()
    versions = {}
    while pending:
        requirement = Requirement(pending.pop())
        name = canonicalize_name(requirement.name)
        key = (name, tuple(sorted(requirement.extras)))
        if key in seen:
            continue
        seen.add(key)
        distribution = metadata.distribution(name)
        versions[name] = distribution.version
        for value in distribution.requires or []:
            dependency = Requirement(value)
            # Include platform-independent/core and selected extra dependencies.
            # Linux-specific dependencies must be checked by the Linux install gate.
            if not dependency.marker or any(
                dependency.marker.evaluate({"extra": extra})
                for extra in requirement.extras | {""}
            ):
                pending.append(str(dependency))
    target = Path(__file__).resolve().parents[1] / "deploy/runtime-requirements.lock"
    target.write_text(
        "# Local installed version snapshot; no hashes; Linux install/CVE gate still required.\n"
        + "\n".join(f"{name}=={versions[name]}" for name in sorted(versions))
        + "\n",
        encoding="utf-8",
    )
    print(f"Pinned {len(versions)} runtime distributions; no packages installed")


if __name__ == "__main__":
    main()
