import hashlib
import io
from datetime import datetime

import requests
from minio import Minio
from qbu_crawler.config import (
    MINIO_ENDPOINT, MINIO_PORT, MINIO_USE_SSL,
    MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_BUCKET, MINIO_PUBLIC_URL,
)


def _get_client() -> Minio:
    return Minio(
        f"{MINIO_ENDPOINT}:{MINIO_PORT}",
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL,
    )


def upload_image(image_url: str) -> str | None:
    """下载图片并上传到 MinIO，返回公开访问 URL。
    如果下载或上传失败，返回 None。
    """
    try:
        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [MinIO] 图片下载失败: {e}")
        return None

    # 用 URL hash 做文件名，避免重复上传
    url_hash = hashlib.md5(image_url.encode()).hexdigest()
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    from qbu_crawler.config import now_shanghai
    month = now_shanghai().strftime("%Y-%m")
    object_name = f"images/{month}/{url_hash}.{ext}"

    client = _get_client()
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)

    data = io.BytesIO(resp.content)
    try:
        client.put_object(
            MINIO_BUCKET,
            object_name,
            data,
            length=len(resp.content),
            content_type=content_type,
        )
    except Exception as e:
        print(f"  [MinIO] 上传失败: {e}")
        return None

    public_url = f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET}/{object_name}"
    return public_url
