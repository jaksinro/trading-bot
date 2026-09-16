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
