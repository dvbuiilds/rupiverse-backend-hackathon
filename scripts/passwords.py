from pathlib import Path


def load_passwords(path: Path) -> dict[str, str]:
    """Read `<file name> = <password>` lines into a {file name: password} map."""
    passwords = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        name, _, password = line.partition(" = ")
        passwords[name.strip()] = password.rstrip("\r")
    return passwords
