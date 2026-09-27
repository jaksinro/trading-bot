import os

import pytest

from tradingbot.process_lock import acquire_lock, release_lock


def test_acquire_lock_creates_file_with_current_pid(tmp_path):
    lock_path = tmp_path / "bot.lock"
    acquire_lock(lock_path)
    assert lock_path.exists()
    assert lock_path.read_text().strip() == str(os.getpid())
    release_lock(lock_path)


def test_acquire_lock_refuses_when_current_process_holds_it(tmp_path):
    lock_path = tmp_path / "bot.lock"
    acquire_lock(lock_path)  # le process courant "tourne" donc detient deja le verrou
    with pytest.raises(SystemExit):
        acquire_lock(lock_path)
    release_lock(lock_path)


def test_acquire_lock_cleans_up_stale_lock_from_dead_pid(tmp_path):
    lock_path = tmp_path / "bot.lock"
    lock_path.write_text("999999999")  # PID quasi certainement inexistant
    acquire_lock(lock_path)  # ne doit pas lever : verrou obsolete remplace
    assert lock_path.read_text().strip() == str(os.getpid())
    release_lock(lock_path)


def test_concurrent_acquire_only_one_wins(tmp_path):
    """Reproduit le bug reel observe : deux lancements au meme instant (ex.
    double-clic sur 'Demarrer') ne doivent PAS tous les deux reussir - la
    creation du verrou doit etre atomique, pas 'verifier puis ecrire'."""
    import threading

    lock_path = tmp_path / "bot.lock"
    barrier = threading.Barrier(2)
    results = []
    results_lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            acquire_lock(lock_path)
            outcome = "acquired"
        except SystemExit:
            outcome = "refused"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["acquired", "refused"]
    release_lock(lock_path)


def test_release_lock_removes_file():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "bot.lock"
        acquire_lock(lock_path)
        release_lock(lock_path)
        assert not lock_path.exists()


# --- EF-82 : detection de processus portable (Raspberry Pi) ----------------
#
# `_is_process_running` ne connaissait que `tasklist` (Windows). Sur Linux la
# commande n'existe pas, l'exception etait avalee et TOUT verrou etait juge
# perime - y compris celui d'un bot vivant : anti-doublon desactive en
# silence. La branche POSIX est testee ici en simulant `os.kill`, JAMAIS en
# l'appelant : sur Windows, `os.kill(pid, 0)` termine le processus.

from tradingbot import process_lock


def _posix(monkeypatch, kill_behaviour):
    monkeypatch.setattr(process_lock.sys, "platform", "linux")
    monkeypatch.setattr(process_lock.os, "kill", kill_behaviour)


def test_posix_live_process_is_detected(monkeypatch):
    _posix(monkeypatch, lambda pid, sig: None)   # signal 0 accepte = vivant
    assert process_lock._is_process_running(4242) is True


def test_posix_dead_process_is_detected(monkeypatch):
    def dead(pid, sig):
        raise ProcessLookupError
    _posix(monkeypatch, dead)
    assert process_lock._is_process_running(4242) is False


def test_posix_process_of_another_user_counts_as_alive(monkeypatch):
    """EPERM = le processus existe mais ne nous appartient pas : il tourne."""
    def forbidden(pid, sig):
        raise PermissionError
    _posix(monkeypatch, forbidden)
    assert process_lock._is_process_running(4242) is True


def test_posix_never_calls_tasklist(monkeypatch):
    """Le symptome d'origine : sur Linux, `tasklist` n'existe pas. Il ne doit
    jamais etre tente hors Windows."""
    called = []
    monkeypatch.setattr(process_lock.subprocess, "run", lambda *a, **k: called.append(a) or None)
    _posix(monkeypatch, lambda pid, sig: None)
    process_lock._is_process_running(4242)
    assert called == []


def _write_lock_before_boot(lock_path, pid):
    """Verrou date d'AVANT le dernier demarrage de la machine."""
    from tradingbot.process_lock import _boot_time

    lock_path.write_text(str(pid))
    boot = _boot_time()
    assert boot is not None
    os.utime(lock_path, (boot - 3600, boot - 3600))


def test_boot_time_is_in_the_past():
    import time

    from tradingbot.process_lock import _boot_time

    assert _boot_time() < time.time()


def test_lock_from_before_reboot_with_reused_pid_is_stale(tmp_path):
    """Bug reel du 2026-09-27 : apres un redemarrage, le PID du verrou de la
    veille designait un svchost bien vivant. Ici le PID est celui du process
    de test, donc 'vivant' : seul l'age du verrou permet de le juger perime."""
    from tradingbot.process_lock import lock_owner

    lock_path = tmp_path / "control_server.lock"
    _write_lock_before_boot(lock_path, os.getpid())
    assert lock_owner(lock_path) is None
    acquire_lock(lock_path)  # ne doit pas lever : le serveur doit pouvoir redemarrer
    assert lock_path.read_text().strip() == str(os.getpid())
    release_lock(lock_path)


def test_fresh_lock_of_live_process_is_honoured(tmp_path):
    from tradingbot.process_lock import lock_owner

    lock_path = tmp_path / "bot.lock"
    lock_path.write_text(str(os.getpid()))
    assert lock_owner(lock_path) == os.getpid()


def test_server_never_kills_the_pid_of_a_stale_bot_lock(tmp_path, monkeypatch):
    """'Arreter' sur un bot au verrou perime ne doit jamais lancer taskkill :
    le PID peut designer un service Windows."""
    from tradingbot import control_server

    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    _write_lock_before_boot(tmp_path / "bot_X.lock", os.getpid())
    calls = []
    monkeypatch.setattr(control_server.subprocess, "run", lambda *a, **k: calls.append(a))
    assert control_server.is_bot_running("X") is False
    control_server.kill_by_name("X")
    assert calls == []
