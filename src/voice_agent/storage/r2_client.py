"""Cloudflare R2 storage for call recordings.

R2 is S3-compatible, so we use boto3 with a custom endpoint URL.
R2's zero egress fees mean dashboard playback costs nothing in bandwidth.

Documentation:
    https://developers.cloudflare.com/r2/examples/aws/boto3/
    https://developers.cloudflare.com/r2/api/s3/api/
"""

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from loguru import logger

from voice_agent.observability.retry import retry_standard


class R2Storage:
    """Upload and retrieve call recordings from Cloudflare R2."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
    ) -> None:
        self._bucket = bucket_name
        self._client = boto3.client(
            service_name="s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

    @retry_standard
    async def upload_recording(
        self,
        call_uuid: str,
        audio_bytes: bytes,
        content_type: str = "audio/mpeg",
    ) -> str:
        """Upload a recording to R2. Returns the object key.

        Args:
            call_uuid: Vobiz call UUID, used as the object name.
            audio_bytes: Raw audio content (Vobiz serves MP3 by default).
            content_type: MIME type stored on the object.

        Returns:
            The R2 object key, e.g. "recordings/abc-123.mp3".
        """
        key = f"recordings/{call_uuid}.mp3"
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=audio_bytes,
                ContentType=content_type,
            )
            logger.info(f"R2: uploaded {len(audio_bytes)} bytes to {key}")
            return key
        except ClientError as e:
            logger.error(f"R2 upload failed for {call_uuid}: {e}")
            raise

    def generate_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        """Generate a temporary public URL for playback.

        Presigned URLs let the frontend fetch recordings without
        exposing R2 credentials.
        """
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    @retry_standard
    async def delete_recording(self, key: str) -> None:
        """Delete a recording (used for retention / DPDP compliance)."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.info(f"R2: deleted {key}")
        except ClientError as e:
            logger.error(f"R2 delete failed for {key}: {e}")
            raise
