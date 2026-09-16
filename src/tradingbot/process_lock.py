"""Verrou de process (fichier PID) pour empecher de lancer deux instances
du meme bot en parallele - elles finiraient par se marcher dessus (memes
ordres passes en double sur le meme compte, ecritures concurrentes en base).

La creation du verrou est ATOMIQUE (O_CREAT | O_EXCL) : si deux lancements
arrivent au meme instant (ex. double-clic sur "Demarrer" avant que le bouton
ne soit desactive), un simple "si le fichier n'existe pas, je l'ecris" laisse
passer les deux (le fichier n'existe encore pour aucun des deux au moment de
la verification). L'ecriture atomique garantit qu'un seul des deux gagne la
creation, l'autre echoue immediatement - bug reel observe en usage (plusieurs
bots tournant systematiquement en double)."""

import atexit
import os
import subprocess
from pathlib import Path


def _is_process_running(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def acquire_lock(lock_path: Path) -> None:
    """Leve SystemExit si une instance est deja active. Nettoie tout seul
    un verrou laisse par un crash (process mort mais fichier pas supprime)."""
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pass
        else:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            atexit.register(release_lock, lock_path)
            return

        try:
            existing_pid = int(lock_path.read_text().strip())
        except (ValueError, FileNotFoundError):
            existing_pid = None

        if existing_pid is not None and _is_process_running(existing_pid):
            raise SystemExit(
                f"Une instance tourne deja (PID {existing_pid}, verrou {lock_path.name}). "
                f"Ferme-la avant d'en relancer une nouvelle. "
                f"Si c'est une erreur (le process n'existe plus), supprime le fichier {lock_path}."
            )

        try:
            lock_path.unlink()  # verrou obsolete (le process precedent est mort), on le remplace
        except FileNotFoundError:
            pass  # deja supprime par un concurrent - on retente simplement


def release_lock(lock_path: Path) -> None:
    try:
        if lock_path.exists() and lock_path.read_text().strip() == str(os.getpid()):
            lock_path.unlink()
    except Exception:
        pass
