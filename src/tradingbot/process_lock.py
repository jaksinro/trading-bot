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
import sys
import time
from pathlib import Path

# Marge sur l'heure de demarrage : GetTickCount64 et l'horloge murale ne sont
# pas lues au meme instant, et le systeme de fichiers arrondit les dates.
BOOT_TOLERANCE_SECONDS = 5


def _is_process_running(pid: int) -> bool:
    """EF-82 : cette fonction ne connaissait que `tasklist` (Windows). Sur
    Linux la commande n'existe pas, l'exception etait avalee et la reponse
    etait toujours "mort" - donc TOUT verrou etait juge perime et supprime,
    y compris celui d'un bot bien vivant : le garde-fou anti-doublon aurait
    ete silencieusement desactive sur le Raspberry Pi. Sur POSIX, le signal
    0 teste l'existence d'un processus sans rien lui envoyer."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # existe, mais appartient a un autre utilisateur
        except Exception:
            return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _boot_time() -> float | None:
    """Instant du dernier demarrage de la machine (epoch), ou None si inconnu."""
    try:
        if sys.platform == "win32":
            import ctypes

            uptime = ctypes.windll.kernel32.GetTickCount64() / 1000
        else:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return None
    return time.time() - uptime


def lock_owner(lock_path: Path) -> int | None:
    """PID du process qui detient REELLEMENT ce verrou, ou None s'il est perime.

    Bug reel constate le 2026-09-27 : apres un redemarrage de Windows, le PID
    ecrit dans `control_server.lock` la veille (14860) avait ete reattribue a
    un `svchost`. "Un process avec ce numero existe" suffisait a juger le
    verrou valide : le serveur refusait de demarrer, la relance automatique
    abandonnait, et aucun bot ne repartait. Pire, "Arreter" sur un bot au
    verrou perime aurait tue ce service Windows (`taskkill /F` sur le PID).
    Un verrou ecrit AVANT le dernier demarrage de la machine est forcement
    perime, quel que soit le PID qu'il contient."""
    try:
        pid = int(lock_path.read_text().strip())
        written_at = lock_path.stat().st_mtime
    except (ValueError, OSError):
        return None
    boot = _boot_time()
    if boot is not None and written_at < boot - BOOT_TOLERANCE_SECONDS:
        return None
    return pid if _is_process_running(pid) else None


def acquire_lock(lock_path: Path) -> None:
    """Leve SystemExit si une instance est deja active. Nettoie tout seul
    un verrou laisse par un crash (process mort mais fichier pas supprime)
    ou par un redemarrage de la machine (PID reattribue, voir `lock_owner`)."""
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

        existing_pid = lock_owner(lock_path)
        if existing_pid is not None:
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
