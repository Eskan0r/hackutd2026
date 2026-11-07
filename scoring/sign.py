# Evidence integrity and report signing (ARCHITECTURE.md D8, §9.6).
#   check_chain      verify prev_sha256 links in one events file
#   evidence_sha256  one hash over all events files, embedded in the signed report
#   sign/verify      ed25519 over canonical JSON (sorted keys, no whitespace)

import base64
import glob
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ZERO = "0" * 64  # prev_sha256 of a file's first line; must match ares/events.py


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


# Returns the first 1-based line whose prev_sha256 mismatches, or None if intact.
# Line N failing => line N-1 edited (or N's seal forged). Edits to the last line are
# undetectable by the chain alone; evidence_sha256 in the signed report covers that.
def check_chain(path: str) -> int | None:
    prev = ZERO
    with open(path, "rb") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    for i, line in enumerate(lines, 1):
        if json.loads(line).get("prev_sha256") != prev:
            return i
        prev = hashlib.sha256(line).hexdigest()
    return None


# Hash over all *.jsonl (sorted by name, name-prefixed) plus per-file chain status.
def evidence_sha256(events_dir: str) -> tuple[str, dict[str, int | None]]:
    h = hashlib.sha256()
    chains = {}
    for path in sorted(glob.glob(os.path.join(events_dir, "*.jsonl"))):
        with open(path, "rb") as f:
            h.update(os.path.basename(path).encode() + b"\0" + f.read())
        chains[os.path.basename(path)] = check_chain(path)
    return h.hexdigest(), chains


def keygen(key_path: str, pub_path: str) -> None:
    key = Ed25519PrivateKey.generate()
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(pub_path, "wb") as f:
        f.write(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


# Returns {"report": ..., "alg": "ed25519", "signature": base64}.
def sign_report(report: dict, key_path: str) -> dict:
    with open(key_path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    sig = key.sign(canonical(report))
    return {"report": report, "alg": "ed25519", "signature": base64.b64encode(sig).decode()}


def verify_report(signed: dict, pub_path: str) -> bool:
    with open(pub_path, "rb") as f:
        pub = serialization.load_pem_public_key(f.read())
    assert isinstance(pub, Ed25519PublicKey)
    try:
        pub.verify(base64.b64decode(signed["signature"]), canonical(signed["report"]))
        return True
    except InvalidSignature:
        return False


# Report body (§9.6) ready to sign. Fix/held-out/reality-check fields get added by the drill orchestrator.
def build_report(score, kills, leakbox_flaws: dict, events_dir: str) -> dict:
    evidence, chains = evidence_sha256(events_dir)
    return {
        "score": score.model_dump(mode="json"),
        "kills": [k.model_dump(mode="json") for k in kills],
        "leakbox_flaws": leakbox_flaws,
        "evidence_sha256": evidence,
        "event_chains_intact": all(v is None for v in chains.values()),
        "event_chain_breaks": {name: line for name, line in chains.items() if line is not None},
        "limitations": [
            f"n={score.n} per cell",
            "twin only; production not observed",
            "evidence of a tested kill path, not a certification",
        ],
    }
