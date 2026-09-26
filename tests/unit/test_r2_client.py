"""Round-trip test for the R2 storage client."""

import asyncio

from voice_agent.config.settings import get_settings
from voice_agent.storage.r2_client import R2Storage


async def main() -> None:
    s = get_settings()
    r2 = R2Storage(
        account_id=s.r2_account_id,
        access_key_id=s.r2_access_key_id,
        secret_access_key=s.r2_secret_access_key,
        bucket_name=s.r2_bucket_name,
    )

    # Small dummy payload (1 KB of silence-ish bytes)
    payload = b"\x00" * 1024
    test_uuid = "test-r2-roundtrip-001"

    key = await r2.upload_recording(test_uuid, payload)
    print(f"Uploaded: {key}")

    url = r2.generate_presigned_url(key, expires_in=60)
    assert "X-Amz-Signature" in url, "Presigned URL missing signature"
    print(f"Presigned URL: {url[:80]}...")

    await r2.delete_recording(key)
    print("R2 client round-trip passed")


if __name__ == "__main__":
    asyncio.run(main())
