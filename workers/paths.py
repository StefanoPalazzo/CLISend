"""Shared-path containment helpers for Clisend workers."""

from pathlib import Path


def resolve_shared_path(shared_folder: str, rel_path: str, *, allow_root: bool = False) -> str:
    """Resolve an application path and ensure it stays inside ``shared_folder``.

    Client paths use ``/`` as the shared-folder root, so a leading slash is
    interpreted relative to that root rather than as an operating-system path.
    """
    root = Path(shared_folder).resolve()
    normalized_path = rel_path.lstrip("/")
    target = (root / normalized_path).resolve()

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Ruta no permitida") from exc

    if target == root and not allow_root:
        raise ValueError("La operación no está permitida sobre la carpeta compartida")

    return str(target)
