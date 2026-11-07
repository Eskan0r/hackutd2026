# Evidence integrity and report signing (ARCHITECTURE.md D8, §9.6).
#   evidence_sha256  one hash over all events files + per-file chain check (ares.events.verify_chain)
#   sign/verify      ed25519 over canonical JSON (sorted keys, no whitespace)

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ares.events import verify_chain


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


# Hash over all *.jsonl (sorted by name, name-prefixed) plus per-file chain problems ([] = intact).
# The chain can't see lines dropped from the end; this hash, embedded in the signed report, can.
def evidence_sha256(events_dir: str) -> tuple:
    h = hashlib.sha256()
    chains = {}
    for path in sorted(glob.glob(os.path.join(events_dir, "*.jsonl"))):
        with open(path, "rb") as f:
            h.update(os.path.basename(path).encode() + b"\0" + f.read())
        chains[os.path.basename(path)] = verify_chain(path)
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


# Report body (§9.6) ready to sign. Fix/held-out fields get added by the drill orchestrator.
def build_report(score, kills, leakbox_flaws: dict, events_dir: str) -> dict:
    evidence, chains = evidence_sha256(events_dir)
    return {
        "score": score.model_dump(mode="json"),
        "kills": [k.model_dump(mode="json") for k in kills],
        "leakbox_flaws": leakbox_flaws,
        "evidence_sha256": evidence,
        "event_chains_intact": all(not problems for problems in chains.values()),
        "event_chain_problems": {name: p for name, p in chains.items() if p},
        "limitations": [
            "n=%d per cell" % score.n,
            "twin only; production not observed",
            "evidence of a tested kill path, not a certification",
        ],
    }
