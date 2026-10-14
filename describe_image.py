#!/usr/bin/env python3
"""Describe an image URL with a local vision model and emit catalog-ready tags.

Supports Ollama's generate endpoint and OpenAI-compatible chat-completions
endpoints. The model endpoint must resolve only to a loopback address.
"""

import argparse
import base64
import getpass
import ipaddress
import json
import os
import socket
import sys
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_MAX_BYTES = 20 * 1024 * 1024
PROMPT = """Analyze this image for a private media catalog. Return JSON only, with this exact shape:
{"description":"one concise factual sentence","tags":["lowercase tag", "another tag"]}

Use 3 to 12 specific, factual tags. Include visible subjects, setting, style, colors, and medium when clear.
Do not identify people, infer protected traits, invent context, or use hashtags."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_url", nargs="?", help="HTTP(S) URL of one image to describe")
    parser.add_argument(
        "--untagged",
        action="store_true",
        help="Describe every untagged image returned by the imageboard API",
    )
    parser.add_argument(
        "--imageboard-url",
        help="Imageboard base URL, required with --untagged (for example https://127.0.0.1:8443)",
    )
    parser.add_argument("--imageboard-user", default=os.environ.get("IMAGEBOARD_USER", ""))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply generated tags to untagged images. Without this flag, output is read-only.",
    )
    parser.add_argument(
        "--comment-description",
        action="store_true",
        help="With --apply, also add each generated description as an image comment.",
    )
    parser.add_argument("--model", default="gemma3", help="Local vision model name")
    parser.add_argument(
        "--api",
        choices=("ollama", "openai"),
        default="ollama",
        help="Model API protocol (default: ollama)",
    )
    parser.add_argument(
        "--endpoint",
        help="Local model endpoint. Defaults to Ollama or OpenAI-compatible loopback endpoint.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Maximum downloaded image size in bytes (default: {DEFAULT_MAX_BYTES})",
    )
    parser.add_argument("--timeout", type=float, default=60, help="Network timeout in seconds (default: 60)")
    args = parser.parse_args()
    if bool(args.image_url) == args.untagged:
        parser.error("supply one image_url or --untagged")
    if args.untagged and not args.imageboard_url:
        parser.error("--untagged requires --imageboard-url")
    if args.apply and not args.untagged:
        parser.error("--apply is only available with --untagged")
    if args.comment_description and not args.apply:
        parser.error("--comment-description requires --apply")
    return args


def default_endpoint(api: str) -> str:
    if api == "ollama":
        return "http://127.0.0.1:11434/api/generate"
    return "http://127.0.0.1:11434/v1/chat/completions"


def require_local_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("model endpoint must be an absolute HTTP(S) URL")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)}
    except socket.gaierror as error:
        raise ValueError("could not resolve model endpoint") from error
    if not addresses or any(not ipaddress.ip_address(address).is_loopback for address in addresses):
        raise ValueError("model endpoint must resolve only to loopback addresses")


def download_image(image_url: str, max_bytes: int, timeout: float, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("image URL must use HTTP or HTTPS")
    if max_bytes < 1:
        raise ValueError("max-bytes must be positive")
    request_headers = {"User-Agent": "imageboard-local-vlm/1"}
    if headers:
        request_headers.update(headers)
    request = Request(image_url, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError("image exceeds max-bytes")
            data = response.read(max_bytes + 1)
    except HTTPError as error:
        raise ValueError(f"image download failed with HTTP {error.code}") from error
    except URLError as error:
        raise ValueError("image download failed") from error
    if len(data) > max_bytes:
        raise ValueError("image exceeds max-bytes")
    if not data:
        raise ValueError("image download was empty")
    if not content_type.startswith("image/"):
        suffix = PurePosixPath(parsed.path).suffix.lower()
        content_type = {
            ".avif": "image/avif",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".webp": "image/webp",
        }.get(suffix, "")
    if not content_type:
        raise ValueError("download did not identify itself as an image")
    return data, content_type


def post_json(endpoint: str, payload: dict, timeout: float) -> dict:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise ValueError(f"model request failed with HTTP {error.code}") from error
    except (URLError, json.JSONDecodeError) as error:
        raise ValueError("model returned an invalid response") from error


def imageboard_credentials(username: str) -> dict[str, str]:
    username = username or input("Imageboard username: ")
    password = getpass.getpass("Imageboard password: ")
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def imageboard_json(url: str, headers: dict[str, str], timeout: float) -> dict:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise ValueError(f"imageboard request failed with HTTP {error.code}") from error
    except (URLError, json.JSONDecodeError) as error:
        raise ValueError("imageboard returned an invalid response") from error


def untagged_images(base_url: str, headers: dict[str, str], timeout: float) -> list[dict]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("imageboard URL must be an absolute HTTP(S) URL")
    items: list[dict] = []
    page = 1
    while True:
        query = urlencode({"untagged": "true", "page": page, "limit": 100})
        response = imageboard_json(f"{base_url.rstrip('/')}/api/images?{query}", headers, timeout)
        batch = response.get("items")
        if not isinstance(batch, list):
            raise ValueError("imageboard response did not contain images")
        items.extend(item for item in batch if isinstance(item, dict) and item.get("kind") == "image")
        if not batch or page * int(response.get("limit", 100)) >= int(response.get("total", 0)):
            return items
        page += 1


def apply_context(base_url: str, image_id: int, tags: list[str], description: str, include_comment: bool, headers: dict[str, str], timeout: float) -> None:
    payload: dict[str, object] = {"tags": tags}
    if include_comment and description:
        payload["comment"] = description
    request_headers = {**headers, "Content-Type": "application/json"}
    request = Request(
        f"{base_url.rstrip('/')}/api/images/{image_id}/context",
        data=json.dumps(payload).encode(),
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout):
            return
    except HTTPError as error:
        raise ValueError(f"tag update failed with HTTP {error.code}") from error
    except URLError as error:
        raise ValueError("tag update failed") from error


def model_response(api: str, endpoint: str, model: str, image: bytes, content_type: str, timeout: float) -> str:
    encoded = base64.b64encode(image).decode("ascii")
    if api == "ollama":
        payload = {
            "model": model,
            "prompt": PROMPT,
            "images": [encoded],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        response = post_json(endpoint, payload, timeout)
        text = response.get("response")
    else:
        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}},
                    ],
                }
            ],
        }
        response = post_json(endpoint, payload, timeout)
        try:
            text = response["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            raise ValueError("model response did not contain a completion") from error
    if not isinstance(text, str):
        raise ValueError("model response did not contain text")
    return text


def normalize_result(text: str) -> dict[str, object]:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {"description": text, "tags": []}
    description = " ".join(str(result.get("description", "")).split()).encode("utf-8")[:8192].decode("utf-8", errors="ignore")
    tags: list[str] = []
    for value in result.get("tags", []):
        tag = " ".join(str(value).lower().split())
        if tag and len(tag) <= 100 and "/" not in tag and "\\" not in tag and not any(char.isspace() and char not in " " for char in tag):
            if tag not in tags:
                tags.append(tag)
        if len(tags) == 50:
            break
    return {"description": description, "tags": tags}


def main() -> int:
    args = parse_args()
    endpoint = args.endpoint or default_endpoint(args.api)
    try:
        require_local_endpoint(endpoint)
        if not args.untagged:
            image, content_type = download_image(args.image_url, args.max_bytes, args.timeout)
            result = normalize_result(model_response(args.api, endpoint, args.model, image, content_type, args.timeout))
            print(json.dumps(result, ensure_ascii=False))
            return 0

        headers = imageboard_credentials(args.imageboard_user)
        items = untagged_images(args.imageboard_url, headers, args.timeout)
        for item in items:
            image_url = urljoin(f"{args.imageboard_url.rstrip('/')}/", str(item["media_url"]).lstrip("/"))
            image, content_type = download_image(image_url, args.max_bytes, args.timeout, headers)
            result = normalize_result(model_response(args.api, endpoint, args.model, image, content_type, args.timeout))
            image_id = int(item["id"])
            if args.apply:
                apply_context(
                    args.imageboard_url,
                    image_id,
                    result["tags"],
                    result["description"],
                    args.comment_description,
                    headers,
                    args.timeout,
                )
            print(json.dumps({"image_id": image_id, **result}, ensure_ascii=False))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
