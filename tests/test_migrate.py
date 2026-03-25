import pytest
from app.models import Peer, PeerStatus
from app.crypto import encrypt_private_key
from scripts.migrate_encrypt_keys import migrate


@pytest.mark.asyncio
async def test_migrate_encrypts_plaintext(session):
    peer = Peer(
        user_id=1, iface="wg0", public_key="pk1",
        private_key_enc="plaintext_key_abc123",
        address="10.10.0.2/32", allowed_ips="10.10.0.2/32",
        status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()

    await migrate()

    await session.refresh(peer)
    assert peer.private_key_enc != "plaintext_key_abc123"
    assert peer.private_key_enc.startswith("gA")


@pytest.mark.asyncio
async def test_migrate_skips_already_encrypted(session):
    encrypted = encrypt_private_key("my_secret_key")
    peer = Peer(
        user_id=1, iface="wg0", public_key="pk2",
        private_key_enc=encrypted,
        address="10.10.0.3/32", allowed_ips="10.10.0.3/32",
        status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()

    await migrate()

    await session.refresh(peer)
    assert peer.private_key_enc == encrypted
