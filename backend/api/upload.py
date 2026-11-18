"""Read a PR batch CSV out of a request, however it was sent (G1): a multipart upload under any field name,
a raw CSV body (text/csv, text/plain, application/octet-stream or no content type), a form field holding the
CSV text, or JSON with the CSV text in a "csv" field."""
import json

from fastapi import HTTPException, Request


def decode(data):
    """UTF-8 (with or without a byte-order mark), falling back to Windows-1252 for spreadsheet exports."""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


async def read_batch(request: Request):
    """(filename, csv_text). 400 with a plain message if there is no CSV in the request."""
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        for key, value in form.multi_items():
            if hasattr(value, "read"):
                return value.filename or key, decode(await value.read())
        for key, value in form.multi_items():
            if isinstance(value, str) and "\n" in value.strip():
                return key, value
        raise HTTPException(400, "The upload contained no file. Send the PR batch CSV as a file field, "
                                 "as the raw request body, or as JSON {\"csv\": \"...\"}.")
    body = await request.body()
    if ctype.startswith("application/json"):
        try:
            payload = json.loads(decode(body) or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"The JSON body could not be read: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("csv"), str):
            raise HTTPException(400, "The JSON body needs a \"csv\" field holding the PR batch CSV text.")
        return payload.get("filename") or "batch.csv", payload["csv"]
    text = decode(body)
    if not text.strip():
        raise HTTPException(400, "The request contained no CSV. Send the PR batch CSV as the body, as a file "
                                 "upload, or as JSON {\"csv\": \"...\"}.")
    return request.headers.get("x-filename") or "batch.csv", text
