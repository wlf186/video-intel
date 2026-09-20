"""Linux process identity independent of wall-clock corrections."""

from pathlib import Path


def token(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    return {
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "start_ticks": fields[19],
    }
