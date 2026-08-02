This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Uploading documents

The **Upload** button on the home/search pages lets you send a local file
straight to Cloudflare R2 and automatically start processing it:

1. The browser asks the API for a presigned PUT URL
   (`GET /api/documents/upload-url/{file_path}`).
2. The file is uploaded directly from the browser to R2 — it never passes
   through the API server.
3. As soon as the upload completes, the browser automatically triggers
   processing (`POST /api/documents/{job_id}/process`) so the document is
   embedded and searchable without any further user action. Transient
   failures (network errors / 5xx) are retried up to 3 times with a short
   backoff; a permanently failed dispatch is surfaced in the UI with a
   **Retry** action.

### Organization and user IDs

The upload endpoint requires `organization_id` and `user_id` query params,
but the web app does not have authentication yet. Both are **required**
and must be configured as environment variables:

- `NEXT_PUBLIC_ORGANIZATION_ID`
- `NEXT_PUBLIC_USER_ID`

Set them in `.env.local` (or the docker-compose environment). If either is
missing, the upload flow fails with a clear error.

### Upload states and troubleshooting

The banner under the **Upload** button always reflects the true state of
the operation:

- **Green (success)** — the file is in R2 and processing has been
  dispatched.
- **Amber (partial)** — the file is in R2, but dispatching processing
  failed after all automatic retries. The file is safe; press **Retry** to
  dispatch processing again (safe: the backend refuses to double-process).
- **Red (error)** — the upload itself failed. Common causes:
  - Missing `NEXT_PUBLIC_ORGANIZATION_ID` / `NEXT_PUBLIC_USER_ID`.
  - The API (`NEXT_PUBLIC_API_URL`) or R2 is unreachable.
  - A PUT that takes longer than 5 minutes (the client-side timeout) or
    longer than the presigned URL's validity (1 hour).

All failure points are logged to the browser console with an `[upload]`
prefix — filter on that string in devtools to trace a failed upload.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
