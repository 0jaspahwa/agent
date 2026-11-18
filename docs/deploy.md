# Deploying the hosted app (Render)

One Docker web service plus a managed Postgres, described in [`render.yaml`](../render.yaml). On every start the app creates any missing tables and seeds the kit and policy v5.0; this is safe to repeat. You do every step below yourself. Commands are for Git Bash on Windows, run from the repo root.

**Why Render.** Its blueprint file creates the web service, the database and the connection between them from the repo, so the whole setup is reviewable as code. Railway would work equally well: a Docker service with Postgres, never sleeping on its paid plan. It is not clearly better here. - **`render.yaml` uses Render's free plans** (decided 17 Nov). The web service sleeps after 15 idle minutes, and the next request can take up to a minute while it wakes. A free database expires 30 days after it is created, which is well after the review.
- **Before a timed step** (Thursday 10:00, a demo), open `<app>/api/health` once and wait for it to answer, so the evaluators' first request does not hit the cold start.

## 1. Check locally first

1. Run the tests and confirm they pass:
   ```bash
   .venv/Scripts/python -m pytest -q
   ```
2. Start the app and database with Docker (the kit's folders in `data/`, which is mounted read-only):
   ```bash
   docker compose up --build
   ```
3. Open http://localhost:8000. Upload `data/pr_batches/sample_pr_batch.csv` and check that the counts show `SPOT_PO 72`.
4. Stop it with `Ctrl+C`, then:
   ```bash
   docker compose down
   ```

## 2. Check for secrets before the first push

The history was scanned on 2026-11-16 and is clean (see `APPROACH.md`). Run these again before you push:

5. List every `.env`-like file ever committed. Only `.env.example` should appear:
   ```bash
   git log --all --name-only --pretty=format: | sort -u | grep -iE "(^|/)\.env"
   ```
6. Search all history for key-shaped strings. This should print nothing:
   ```bash
   git log --all -p | grep -nE "AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY"
   ```
7. Confirm `.env` is ignored. This should print `.gitignore:2:.env  .env`:
   ```bash
   git check-ignore -v .env
   ```

## 3. Create the public GitHub repository and push

8. On github.com, choose **New repository**. Name it `agent`, set it to **Public**, and **do not** add a README, `.gitignore` or licence. The repo must stay empty.
9. Connect and push:
   ```bash
   git remote add origin https://github.com/0jaspahwa/agent.git
   ```
   ```bash
   git push -u origin main
   ```
10. On GitHub, check that `.env` and `data/` are **not** in the file list (the task kit must not be in the public
    repo) and that `backend/` and `render.yaml` are.

## 4. Create the database and the service on Render

11. Sign in at dashboard.render.com. Choose **New → Blueprint** and connect your GitHub account if asked.
12. Pick the `agent` repo. Render reads `render.yaml` and shows two resources: the database `corvo-db` and the web service `corvo-procurement`.
13. Render asks for the value of **`GEMINI`** (marked `sync: false`). Paste your Gemini API key there. It stays in Render, never in the repo.
14. Check the plans and region it shows, then **Apply**. The database is created first, and its connection string is passed to the service as `DATABASE_URL`.
15. Open the web service's **Logs**. The first build takes a few minutes. Wait for `Application startup complete`.
    The log also says `No kit data loaded`: the image never contains the kit, so the database starts with policy
    v5.0 only.
15a. **Load the kit.** Open `<app>/` in a browser, choose your name and the **Procurement** role, open
    **Load kit data**, choose the kit zip exactly as received (`Cantill_FullStack_Task_Kit_vf.zip`) and press
    **Load kit data**. The page lists the rows added: items 73, suppliers 48, plants 2, PO history 468, contracts
    12 (10 from the register, 2 read from their PDFs), contract lines. The banner "No kit data loaded" disappears.
    Loading the same zip again changes nothing. (Without a browser: `curl -s -H "X-User: Ojas" -H "X-Role:
    Procurement" -F "kit=@Cantill_FullStack_Task_Kit_vf.zip" <app>/api/admin/load-kit`; the plain form is on
    `<app>/ops`.) The kit stays in the Render database across deploys and restarts; only a reset (5a) removes it.

If you prefer to set things up by hand instead of using the blueprint:
- Create a **PostgreSQL** database first.
- Create a **Web Service** with runtime **Docker** from the repo.
- Set the environment variables listed in `render.yaml`: `DATABASE_URL` is the database's *Internal Database URL*, plus `SEED_ON_STARTUP=true`, `LLM_PROVIDER=gemini`, `LLM_MODEL`, `LLM_MODELS` and `GEMINI`.
- Set the health check path to `/api/health`.

## 5. Check the hosted app

Replace `<app>` with the service URL Render shows, e.g. `https://corvo-procurement.onrender.com`.

16. Health. It should report `"database": "postgresql"`, `"kit_loaded": true` and rows `items 73, suppliers 48, po_history 468, contracts 12, policy_versions 1`:
    ```bash
    curl -s <app>/api/health
    ```
17. Process the sample batch and keep the export:
    ```bash
    curl -s -F "file=@data/pr_batches/sample_pr_batch.csv" "<app>/api/process-batch?format=csv" -o hosted.csv
    ```
18. Compare it with the reviewed golden file. No output means identical:
    ```bash
    git diff --no-index --stat backend/tests/golden/sample_pr_batch_decisions.csv hosted.csv
    ```
19. Preferred-supplier export as of 1 Nov 2026. It should list `ITM-1048` with S029, S030:
    ```bash
    curl -s "<app>/api/preferred-suppliers/export.csv?as_of=2026-11-01" | head
    ```
20. Open `<app>/` in a browser: the interface. Choose a name and the Buyer role, and process the sample batch under Batches. The plain pages are at `<app>/ops`.
21. `curl -s <app>/api/runs` lists the runs. Each shows the deployed commit as `engine_version`.

## 5a. When the database schema changes (reset once)

The app creates missing tables on start but never adds columns to an existing table. After a commit that changes
the schema (new tables are fine; new columns are not), the hosted database must be rebuilt once:

24. In Render, open the web service → **Environment**, set `RESET_DB_ON_START` to `true`, and save.
25. **Manual Deploy → Deploy latest commit**. In the **Logs** you should see
    `RESET_DB_ON_START=true: dropped every table, recreated them and reseeded`.
    Everything stored is gone: runs, drafts, approved amendments, chat requests, contracts added by hand, the audit
    log, **and the kit**.
26. **Immediately** set `RESET_DB_ON_START` back to `false` and save (Render redeploys; that start must not show
    the reset message). Then **load the kit again** (step 15a) and repeat steps 16–18.
27. **Never leave it on after the freeze.** On Thursday a restart (Render restarts free services after they sleep)
    would silently delete Run 2's approved amendment. Check it is `false` before 10:00.

## 6. Freeze for Thursday

22. `render.yaml` sets `autoDeploy: false`, so pushing does not redeploy. When the final commit is pushed, before **Thu 19 Nov 10:00 IST**, choose **Manual Deploy → Deploy latest commit** in Render. Then repeat steps 16–18.
23. After 10:00, push nothing except the `submission/` folder. Pushing it does not redeploy the app.
