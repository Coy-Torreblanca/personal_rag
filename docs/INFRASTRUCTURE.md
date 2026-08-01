# S3 Storage

R2 cloudflare storage.
Use Apple SSO.

# Modal

Use Coy-Torreblanca Github.

## R2 bucket CORS (required for browser uploads/downloads)

The web app uploads files directly to R2 via presigned URLs and downloads
them with `fetch` from the browser. Because those requests are cross-origin
(app origin -> `*.r2.cloudflarestorage.com`), the bucket must have a CORS
policy that allows:

- the origin(s) the app runs on (`http://localhost:3000`, staging, prod)
- `PUT` (uploads) and `GET` (downloads)
- the `Content-Type` header — uploads send a non-safelisted
  `Content-Type` (e.g. `text/markdown`), so the browser fires a CORS
  **preflight** (`OPTIONS`) before the actual PUT, and the presigned URL is
  signed with `content-type` in `X-Amz-SignedHeaders`, so the header cannot
  simply be dropped

**Without this policy** you will see:

- Safari: `Failed to load source: preflight response was not successful - status code 403`
- Chrome: `Failed to fetch` / `Response to preflight request doesn't pass access control check`

### Policy (bucket: `30aidev`)

```json
[
  {
    "AllowedOrigins": ["http://localhost:3000"],
    "AllowedMethods": ["GET", "PUT", "DELETE", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

Add every origin the app runs on (dev, staging, prod) to `AllowedOrigins`.
`GET` and `PUT` are the minimum for the current UI (`DELETE`/`HEAD` cover
future direct-to-bucket deletes/head checks).

### Apply

1. **Cloudflare dashboard** — R2 → your bucket → Settings → CORS Policy → edit.
2. **wrangler** — `wrangler r2 bucket cors set 30aidev --cors-file cors.json`
3. **S3 API** — `PUT /?cors=` on the bucket with the same JSON.
