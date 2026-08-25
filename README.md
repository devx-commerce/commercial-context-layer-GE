# Commercial Context Layer — POC

Cross-source (Gmail + Slack) search over policy-approved commercial content, indexed
into a Gemini Enterprise custom data store with per-team ACLs, answered by the native
Gemini Enterprise app with citations. Full design: `personal-notes/GE Commercial
Context Layer POC - Build Spec.md` in the parent repo.

This README is a runnable setup/deploy checklist, not just a description. Commands
assume **Cloud Shell** (has `gcloud`, Python, and a container builder preinstalled —
no local Docker/gcloud install needed).

## What's already built vs. what you run

Everything under `app/`, `scripts/`, `tests/`, `Dockerfile` is finished code. Steps 1–11
below are GCP/Slack/Google console and CLI actions that need your project access and
can't be done from a coding session — this doc gives you the exact command or setting
for each.

## Known POC simplifications

A few deliberate deviations from a literal reading of the build spec, chosen for build
speed. None of them affect the ACL/approval logic — only plumbing details:

1. **PKCE is not implemented** in the Gmail OAuth flow — only an HMAC-signed, expiring
   `state`. PKCE protects public clients that can't hold a secret; this is a
   server-side flow that already holds a client secret in Secret Manager, so it would
   add ceremony without adding real protection.
2. **No proactive encrypted-attachment detection.** Only MIME type and
   `attachment_max_bytes` are checked explicitly; anything else that fails to process
   (encrypted or otherwise) is just logged as a generic, content-free error counter.
3. **`jobs/reconcile.py` was dropped.** It's listed in the build spec's file layout but
   never defined anywhere in the spec (no endpoint, no scheduler, no behavior). In its
   place, `jobs/reindex_domain.py` implements the endpoint the spec *does* define
   (`/internal/reindex-domain`, section 8) but forgot to list in the file layout.
4. **Every Gemini upsert/delete goes through the pending-operations queue exclusively**
   — producers (Gmail/Slack ingestion) never call Gemini directly; only the 5-minute
   `process-pending` job does. This means one retry path instead of two, at the cost of
   up to ~5 extra minutes of latency on a document's very first indexing attempt (well
   inside the 30-minute freshness target). It also means there's no cross-run retry
   counter for true exponential backoff — the strict `pending/operations` schema has no
   field for one — so backoff relies on the Google client libraries' own per-call
   retry behavior plus the fixed 5-minute scheduler cadence.
5. **Slack attachment fetch is always deferred** to that same pending-queue job, never
   attempted inline during the webhook request — one code path, and no risk of missing
   Slack's short ack window.
6. **The Gemini Enterprise data store is created by hand in the console**, not scripted
   — see step 4. It's a one-time action with a handful of settings; scripting the
   Discovery Engine API for it adds more risk than it saves for something done once.
7. **No Terraform, no CI/CD.** Deploy is a single `gcloud run deploy --source .`.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

These tests cover only the pure-logic modules (config validation, ACL algorithm,
domain-match policy, document ID hashing, HTML sanitization) — no GCP access needed.
Everything that talks to Gmail/Slack/GCS/Gemini can only be verified after deployment
(step 11).

---

## Setup & deploy runbook

Set these once in your Cloud Shell session:

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export BUCKET="commercial-context-poc-${PROJECT_ID}"
export SERVICE_NAME=commercial-context-layer
export RUNTIME_SA="commercial-context-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
export SCHEDULER_SA="commercial-context-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
```

### 1. Confirm Gemini Enterprise / Discovery Engine access

The biggest external risk in this whole build. Before anything else: in GCP Console,
go to **Gemini Enterprise** (or **Agentspace** / **Vertex AI Search**, depending on your
console's current naming) and confirm you can create a data store. If it's gated or
needs allowlisting on your project, sort that out first — everything else here is
useless without it.

### 2. Bootstrap the GCP project

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  discoveryengine.googleapis.com \
  storage.googleapis.com

gsutil mb -l "$REGION" -b on "gs://${BUCKET}"   # -b on = uniform bucket-level access

gcloud iam service-accounts create commercial-context-runtime \
  --display-name "Commercial Context Layer runtime"
gcloud iam service-accounts create commercial-context-scheduler \
  --display-name "Commercial Context Layer scheduler caller"

gsutil iam ch "serviceAccount:${RUNTIME_SA}:roles/storage.objectAdmin" "gs://${BUCKET}"

# Broad on purpose for POC speed: the OAuth callback creates a Secret Manager secret
# per new Gmail user at runtime, which needs secrets.create + secrets.versions.add at
# the project level. Narrow this to a custom role before this goes anywhere near prod.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/discoveryengine.editor"
```

### 3. Create placeholder secrets

Real values for the OAuth client and Slack app land here after steps 6–7; the
state-signing key is self-contained and can be generated right now.

```bash
echo -n '{"client_id":"REPLACE_ME","client_secret":"REPLACE_ME"}' | \
  gcloud secrets create gmail-oauth-client --data-file=-

python3 -c "import secrets; print(secrets.token_urlsafe(32))" | \
  gcloud secrets create oauth-state-signing-key --data-file=-

echo -n "REPLACE_ME" | gcloud secrets create slack-bot-token --data-file=-
echo -n "REPLACE_ME" | gcloud secrets create slack-signing-secret --data-file=-
```

### 4. Create the Gemini Enterprise data store + app (console)

Create one **custom, unstructured** data store with:

- content required; ACL enabled at creation (this is what makes per-team access work —
  it cannot be turned on later);
- layout-based chunking enabled at creation, chunk size **350** tokens, include
  ancestor headings: **true**;
- default parser: **layout**; PDF override: **OCR with native text enabled**; DOCX
  override: **layout parser**.

Then create a native Gemini Enterprise **app** on top of that store, and set its
instructions to exactly what's in build spec section 15 (answer only from retrieved
documents, cite every claim, say when evidence is insufficient, don't infer job
function from a name, prefer the most recent explicit timestamp for "latest status").

Note the data store ID — you'll set it as `DISCOVERYENGINE_DATA_STORE_ID` below.

### 5. First deploy (to learn the service URL)

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region="$REGION" \
  --service-account="$RUNTIME_SA" \
  --allow-unauthenticated \
  --max-instances=1 \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},GCS_BUCKET=${BUCKET},GMAIL_OAUTH_CLIENT_SECRET=projects/${PROJECT_ID}/secrets/gmail-oauth-client,OAUTH_STATE_SIGNING_SECRET=projects/${PROJECT_ID}/secrets/oauth-state-signing-key,SLACK_BOT_TOKEN_SECRET=projects/${PROJECT_ID}/secrets/slack-bot-token,SLACK_SIGNING_SECRET_SECRET=projects/${PROJECT_ID}/secrets/slack-signing-secret,DISCOVERYENGINE_DATA_STORE_ID=<data-store-id-from-step-4>"

export SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format='value(status.url)')
echo "$SERVICE_URL"
```

`--allow-unauthenticated` is intentional and matches the spec, not a shortcut: `/oauth/*`
and `/webhooks/slack/events` must be publicly reachable (Google and Slack don't present
Cloud Run invoker identities), while `/internal/*` enforces its own OIDC check in
application code (`app/auth/scheduler_auth.py`) — that's the real gate, independent of
Cloud Run's IAM layer.

`curl "$SERVICE_URL/health"` should return `{"status":"ok"}`.

### 6. Create the Google OAuth client (console)

APIs & Services → Credentials → **Create OAuth client ID** → Web application.

- Authorized redirect URI: `${SERVICE_URL}/oauth/gmail/callback`
- Scopes requested by the app at runtime: `openid email profile
  https://www.googleapis.com/auth/gmail.readonly`

Then:

```bash
echo -n '{"client_id":"<id>","client_secret":"<secret>"}' | \
  gcloud secrets versions add gmail-oauth-client --data-file=-
```

### 7. Create the Slack app (console)

Go to <https://api.slack.com/apps> → **Create New App** → **From a manifest**, and paste
`slack-app-manifest.yaml` from this repo. It intentionally omits `event_subscriptions`
entirely — see the comment in that file for why (Slack requires bot event types to be
paired with a Request URL or Socket Mode at declaration time, and we can't supply a
real Request URL until the real signing secret is in place). Install the app to your
workspace, then:

```bash
echo -n "<bot-token-starting-with-xoxb->" | gcloud secrets versions add slack-bot-token --data-file=-
echo -n "<signing-secret-from-basic-information-page>" | gcloud secrets versions add slack-signing-secret --data-file=-
```

Redeploy so the running instance picks up the real values (module-level in-process
caches mean a live instance won't otherwise see a new secret version):

```bash
gcloud run deploy "$SERVICE_NAME" --source . --region="$REGION"
```

Now go back to the Slack app's **Event Subscriptions** page and: turn Events on, set the
request URL to `${SERVICE_URL}/webhooks/slack/events` (Slack's verification challenge
should now pass since the real signing secret is in place), then add `message.channels`
and `message.groups` under bot events, and save.

### 8. Second deploy (full env, including the scheduler audience)

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region="$REGION" \
  --service-account="$RUNTIME_SA" \
  --allow-unauthenticated \
  --max-instances=1 \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},GCS_BUCKET=${BUCKET},OIDC_AUDIENCE=${SERVICE_URL},SCHEDULER_SERVICE_ACCOUNT_EMAIL=${SCHEDULER_SA},GMAIL_OAUTH_CLIENT_SECRET=projects/${PROJECT_ID}/secrets/gmail-oauth-client,OAUTH_STATE_SIGNING_SECRET=projects/${PROJECT_ID}/secrets/oauth-state-signing-key,SLACK_BOT_TOKEN_SECRET=projects/${PROJECT_ID}/secrets/slack-bot-token,SLACK_SIGNING_SECRET_SECRET=projects/${PROJECT_ID}/secrets/slack-signing-secret,GMAIL_OAUTH_REDIRECT_URI=${SERVICE_URL}/oauth/gmail/callback,DISCOVERYENGINE_DATA_STORE_ID=<data-store-id-from-step-4>"
```

### 9. Write and upload `config/config.json`

Copy `config/config.example.json`, edit teams/accounts/Slack channels for real, then:

```bash
PROJECT_ID="$PROJECT_ID" GCS_BUCKET="$BUCKET" \
  python -m scripts.upload_config config/config.json
```

This runs full section-7 validation first and refuses to upload on any failure. (You
can also dry-run just the shape/rule checks with no GCP access at all:
`python -m scripts.validate_config config/config.json`.)

### 10. Create the two Cloud Scheduler jobs

```bash
gcloud scheduler jobs create http poll-gmail \
  --location="$REGION" --schedule="*/10 * * * *" --http-method=POST \
  --uri="${SERVICE_URL}/internal/poll-gmail" \
  --oidc-service-account-email="$SCHEDULER_SA" --oidc-token-audience="$SERVICE_URL"

gcloud scheduler jobs create http process-pending \
  --location="$REGION" --schedule="*/5 * * * *" --http-method=POST \
  --uri="${SERVICE_URL}/internal/process-pending" \
  --oidc-service-account-email="$SCHEDULER_SA" --oidc-token-audience="$SERVICE_URL"
```

To manually trigger a reindex after changing a team/account's ACL-relevant config
(grant your own account `roles/iam.serviceAccountTokenCreator` on `$SCHEDULER_SA` first):

```bash
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="$SCHEDULER_SA" --audiences="$SERVICE_URL")
curl -X POST -H "Authorization: Bearer $TOKEN" "${SERVICE_URL}/internal/reindex-domain?domain=hindustantimes.com"
```

### 11. Bootstrap Slack channels and onboard the first Gmail user

```bash
PROJECT_ID="$PROJECT_ID" GCS_BUCKET="$BUCKET" SLACK_BOT_TOKEN_SECRET="projects/${PROJECT_ID}/secrets/slack-bot-token" \
  python -m scripts.bootstrap_slack_channels
```

This joins configured public channels and reports which private ones still need a
manual invite from a channel member.

Send a Gmail user to `${SERVICE_URL}/oauth/gmail/start` to complete the read-only
consent flow. Confirm `state/users.json` in the bucket now has their entry, and that
the initial backfill scan ran (check Cloud Run logs, or list
`gs://${BUCKET}/approved/`).

For a Slack-only user who never runs Gmail OAuth:

```bash
PROJECT_ID="$PROJECT_ID" GCS_BUCKET="$BUCKET" \
  python -m scripts.upsert_user new-user@devx.com --teams enterprise-north
```

### 12. Smoke test end to end

1. Send a qualifying test email to/from a configured account domain, and post a message
   in a whitelisted Slack channel.
2. Within a few minutes, check `gs://${BUCKET}/approved/<domain>/...` for the new
   evidence objects.
3. Confirm a corresponding document shows up in the Gemini Enterprise data store.
4. Ask a question in the native Gemini Enterprise app and confirm a grounded answer
   with a citation pointing at that evidence.
