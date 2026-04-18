### 1. The Frontend (Deployed on Vercel)
* **Framework:** Next.js (App Router).
* **Aesthetics:** Tailwind CSS + shadcn/ui (for the sleek, dark-mode Gen Z components) + Framer Motion (for buttery animations).
* **AI State:** Vercel AI SDK (handles the complex streaming UI so you do not have to write custom React hooks for it).

### 2. The Identity Layer
* **Auth & RBAC:** Clerk. It handles B2B organization switching natively ("org auth" to "user auth") and integrates flawlessly with Next.js middleware to protect your routes.

### 3. The Backend API & Workers (Containerized via Docker)
* **Core Framework:** FastAPI. Native async support is non-negotiable for AI streaming and concurrently fetching data from Square.
* **Package Management:** `uv`. It will keep your Python dependency resolution blisteringly fast and your Docker builds incredibly lean.
* **AI Orchestration:** LiteLLM (to standardize API calls so you can swap between OpenAI, Anthropic, or local models without rewriting your routing).
* **Task Queue:** Celery (backed by Redis). Essential for your "AI Folder Merging" node. When an unstructured document is uploaded, FastAPI instantly returns a "success" to the user, while Celery handles the heavy lifting of parsing and embedding in the background.

### 4. The Data Ingestion Pipeline (For Unstructured Data)
* **File Storage:** AWS S3 (or Cloudflare R2 to save on egress costs). This is where the physical PDFs and business plans live.
* **Parsing Engine:** The `unstructured` Python library (or LlamaParse if you want to offload OCR and complex table extraction to an API). This strips the text out of `.docx` and `.pdf` files cleanly so your embedding model can actually read it.

### 5. The Database (The Unified Vault)
* **Primary DB:** PostgreSQL. 
* **Vector Engine:** The `pgvector` extension. 
* **SQLModel** for easy data/code modeling and **Alembic** for data/model synchornization.
* **The Strategy:** Keep it in one place. Your relational data (users, organizations, file metadata, S3 URLs) and your vector embeddings (the mathematical representation of the unstructured text) live in the same database. This allows you to write standard SQL queries with vector similarity functions attached (e.g., "Find the most relevant text chunks *where* the organization_id equals X").

### 6. Infrastructure Deployment
* **The Vibe:** Container-first.
* **Platform Backend:** Render or Railway. You bundle your FastAPI app and Celery workers into clean Docker images and deploy them here. You can easily set up a private network so your backend components can talk to your Postgres/Redis instances securely without touching the public internet.
* **Platform Frontend:** Vercel.
