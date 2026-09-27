"""
mcma.app.first_admin_cli -- offline, single-purpose creation of the FIRST
MCMA Platform administrator.

    python -m mcma.app.first_admin_cli ADMIN_USERNAME

Run by `mcma-deploy.sh create-first-admin` inside a throw-away container of
the built image (no network, no published ports, read-only filesystem, no
capabilities, only the database directory mounted). It is NOT part of the
web application and adds no endpoint.

Safety properties:
  * the password is read twice with getpass (no echo) from a real terminal;
    it is never a command-line argument, never an environment variable and
    never printed or logged -- nor is its hash. A non-interactive stdin is
    refused, so a password cannot be piped in either;
  * the application lock is taken first (the same lock file the server
    holds), so a running server makes this command refuse;
  * it succeeds only when the users table is empty; otherwise it refuses
    and changes nothing;
  * the password is confirmed and validated BEFORE any database write; then
    canonical accounts + user + access to exactly those four accounts + audit
    row are ONE transaction (mcma.app.auth.users.create_first_admin), whose
    first step is re-checking that no user exists -- all or nothing, and a
    refused command has written nothing.

Inputs are two PATHS from the environment (MCMA_DB_PATH,
MCMA_INSTANCE_LOCK_PATH) -- no secret. Messages are French. Exit codes:
0 created, 1 refused/failed, 2 usage.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional, TextIO

from mcma.app.auth import users
from mcma.core.mutex import MutexAcquisitionError, create_single_instance_mutex
from mcma.persistence.db import open_database


def _fail(stderr: TextIO, message: str, code: int = 1) -> int:
    print(f"ERREUR : {message}", file=stderr)
    return code


def run(
    argv: list,
    *,
    environ: Optional[Mapping[str, str]] = None,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    is_tty: Optional[bool] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    mutex_factory: Optional[Callable] = None,
) -> int:
    env = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = argparse.ArgumentParser(
        prog="create-first-admin", add_help=True,
        description="Crée le premier administrateur de la plateforme MCMA (hors ligne).",
    )
    parser.add_argument("username", help="nom d'utilisateur de l'administrateur (le mot de passe est demandé)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) if exit_.code in (0, None) else 2

    try:
        username = users.normalize_username(args.username)
    except users.UserInputError as exc:
        return _fail(stderr, exc.message)

    interactive = sys.stdin.isatty() if is_tty is None else is_tty
    if not interactive:
        return _fail(
            stderr,
            "un terminal interactif est requis : le mot de passe est saisi au clavier, "
            "jamais en argument ni par redirection.",
        )

    db_value, lock_value = env.get("MCMA_DB_PATH"), env.get("MCMA_INSTANCE_LOCK_PATH")
    if not db_value or not lock_value:
        return _fail(stderr, "MCMA_DB_PATH et MCMA_INSTANCE_LOCK_PATH doivent être définis.")
    db_path, lock_path = Path(db_value), Path(lock_value)
    if not db_path.parent.is_dir():
        return _fail(stderr, "le répertoire de la base de données est introuvable.")

    factory = mutex_factory or (lambda path: create_single_instance_mutex("mcma-single-instance", lock_path=path))
    mutex = factory(lock_path)
    try:
        mutex.acquire()
    except MutexAcquisitionError:
        return _fail(stderr, "le serveur MCMA semble en cours d'exécution (verrou déjà pris). Arrêtez-le d'abord.")
    except OSError:
        return _fail(stderr, "le verrou de l'application n'a pas pu être pris.")

    conn = None
    try:
        conn = open_database(db_path)
        # Early READ-ONLY check for a better experience (no pointless prompts).
        # The authoritative check is inside create_first_admin's transaction;
        # nothing has been written yet, canonical accounts included.
        if users.user_count(conn) != 0:
            return _fail(
                stderr,
                "des utilisateurs existent déjà : le premier administrateur ne peut plus être créé. "
                "Rien n'a été modifié.",
            )
        password = getpass_fn("Mot de passe : ")
        confirmation = getpass_fn("Confirmez le mot de passe : ")
        if password != confirmation:
            return _fail(stderr, "les deux mots de passe ne sont pas identiques. Rien n'a été créé.")
        try:
            created = users.create_first_admin(conn, username, password)
        except users.UserInputError as exc:
            return _fail(stderr, exc.message)
        finally:
            password = confirmation = ""         # do not keep the secret around
        print(
            f"Administrateur « {created['username']} » créé avec accès aux "
            f"{len(created['account_ids'])} comptes portail. Vous pouvez démarrer le serveur.",
            file=stdout,
        )
        return 0
    except Exception as exc:
        # Type only: an exception message could carry data.
        return _fail(stderr, f"échec inattendu ({type(exc).__name__}). Rien n'a été créé.")
    finally:
        if conn is not None:
            conn.close()
        mutex.release()


def main() -> None:  # pragma: no cover - entry point
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":  # pragma: no cover
    main()
