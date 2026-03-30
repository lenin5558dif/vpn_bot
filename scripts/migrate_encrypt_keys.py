"""One-time migration: encrypt existing plaintext WireGuard private keys."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import select
from app.database import SessionLocal
from app.models import Peer
from app.crypto import encrypt_private_key


async def migrate() -> None:
    async with SessionLocal() as session:
        res = await session.exec(select(Peer))
        peers = res.all()
        migrated = 0
        for peer in peers:
            # Fernet tokens are ~120+ chars and start with "gA"; WG keys are ~44 chars
            if len(peer.private_key_enc) > 80 and peer.private_key_enc.startswith("gA"):
                continue
            peer.private_key_enc = encrypt_private_key(peer.private_key_enc)
            session.add(peer)
            migrated += 1
        await session.commit()
        print(f"Migrated {migrated} peer(s), skipped {len(peers) - migrated}.")


if __name__ == "__main__":
    asyncio.run(migrate())
