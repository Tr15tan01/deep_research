# Deploying on Render (free)

This uses Render's **native Python and Node runtimes** (no Docker). There are two Blueprints:

| File | Monthly cost on Render | What you get |
| --- | --- | --- |
| [`render.yaml`](../render.yaml) **(default)** | **$0** | Website + API (research and its queue run inside the API), all on free instances. No Key Value needed. |
| [`render.standard.yaml`](../render.standard.yaml) | ~$14 | Always-on private API + separate background worker. See [Upgrading](#upgrading-to-the-standard-layout). |

The free layout creates:

| Resource | Render type | Plan | Role |
| --- | --- | --- | --- |
| `deep-research-web` | Web service (Node) | Free | The website. |
| `deep-research-api` | Web service (Python) | Free | FastAPI **and** the research worker in one process. It has a public URL, but it rejects every request that doesn't carry a secret only the website's server knows. |
| MongoDB | **MongoDB Atlas** (external) | Free M0 | The durable database. Render does not host MongoDB. |

Your only other costs are the AI and search APIs, and both have free tiers (see step 7).

**Free-tier limits** (Render's rules for free instances, see [render.com/docs/free](https://render.com/docs/free)):

- **Sleep**: each service sleeps after 15 minutes without traffic; the next visit takes about a minute to wake it.
  While a research page is open, the page keeps both services awake. If you close it mid-run and everything goes to
  sleep, the job pauses and **resumes from its checkpoint** on your next visit (sleep time doesn't count against the
  job's time limit).
- **750 free hours per month**, shared by both services. They only use hours while awake, so occasional use fits
  easily. Leaving them awake around the clock (for example with an uptime pinger) would use about 1,440 hours and get
  them suspended until the next month, so don't.
- **One research job at a time** on the 512 MB free instance; additional jobs wait in the queue.
- **No email** (free services can't reach SMTP ports) and **no Render Shell**. The steps below avoid needing either.
- **No Redis service.** The API uses `REDIS_URL=memory://`: job delivery, rate limits and caches live in the API
  process and reset when it sleeps or restarts. That's fine: Redis only *delivers* jobs, and pending work is
  re-dispatched from MongoDB automatically. It also means the API must run as a **single instance**. (This avoids
  Render's one-free-Key-Value-per-account limit. If you'd rather use a real Redis, e.g. an existing Key Value or a free
  Upstash database, set `REDIS_URL` to its `redis://`/`rediss://` URL.)

> Render deploys from a Git repository (GitHub, GitLab or Bitbucket). It does not accept uploaded zip or rar files,
> so step 1 is to put this code in a repository.

## 1. Put the code on GitHub

```bash
cd deep-research
git init && git add . && git commit -m "Deep Research"
# create an empty private repo on github.com, then:
git remote add origin https://github.com/YOU/deep-research.git
git branch -M main && git push -u origin main
```

(GitHub Desktop works too: *File → Add local repository → Publish*.)

**Region**: `render.yaml` uses `oregon` (US West) for both services, and the region can't be changed after
creation. For Europe or nearby, change both `region: oregon` lines to `region: frankfurt`, commit and push before
step 3.

## 2. Create the MongoDB Atlas database (free)

1. Sign up at [mongodb.com/atlas](https://www.mongodb.com/cloud/atlas) → **Create** a cluster → **M0 Free**. Pick the
   region matching Render (AWS Oregon `us-west-2` for `oregon`, AWS Frankfurt `eu-central-1` for `frankfurt`).
2. **Database Access** → *Add new database user* → a username and a long generated password → *Read and write to any
   database*.
3. **Network Access** → *Add IP address* → `0.0.0.0/0` (allow from anywhere). Render's outbound addresses are shared
   ranges per region (shown in Render under a service's **Connect → Outbound**); you can narrow the list to those later.
   The long password protects the database either way.
4. **Connect → Drivers** → copy the connection string and put your password in it:
   `mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`
   (if the password contains `@ : / ? #`, URL-encode those characters, or generate one without them).

The app creates its collections and indexes itself on first start.

## 3. Create the Blueprint on Render

1. Render dashboard → **New → Blueprint** → connect GitHub → pick the repository. Leave the Blueprint path empty
   (it uses `render.yaml`).
2. Render asks for three values:

   | Variable | Service | Value |
   | --- | --- | --- |
   | `FRONTEND_URL` | deep-research-api | `https://deep-research-web.onrender.com` |
   | `MONGODB_URI` | deep-research-api | the Atlas string from step 2 |
   | `API_INTERNAL_URL` | deep-research-web | `https://deep-research-api.onrender.com` |

   Render names each site `https://<service-name>.onrender.com`. If a name is taken, it adds a suffix; you'll fix that in
   step 5 if so.
3. **Apply**. The first build takes about 5–10 minutes. `AUTH_SECRET`, `ENCRYPTION_KEYS` and `INTERNAL_PROXY_TOKEN` are
   generated automatically, and the website receives the same `INTERNAL_PROXY_TOKEN` as the API.

## 4. Check it started

- `deep-research-api` → **Logs** shows `embedded_worker_started` and `api_started`. A wrong setting stops startup with an
  exact message (e.g. `FRONTEND_URL must use https`).
- Open `https://deep-research-api.onrender.com/api/v1/public/config` in a browser: it should answer
  *"Direct API access is not allowed."* That's correct, because the API only talks to your website.
- Open the website's URL: you should see the landing page.

## 5. Check both URLs

Look at the URL shown at the top of each service in Render.

- If **deep-research-web**'s URL differs from what you typed: `deep-research-api` → **Environment** → fix
  `FRONTEND_URL` (exact, `https://`, no trailing slash) → **Save, rebuild and deploy**.
  *Symptom if wrong: sign-in fails with "csrf_failed".*
- If **deep-research-api**'s URL differs: `deep-research-web` → **Environment** → fix `API_INTERNAL_URL` → **Save,
  rebuild and deploy**. *Symptom if wrong: "The research service is unreachable."*

## 6. Make yourself admin (no Shell needed)

1. Open the website → **Start researching** → register with your email and a password.
2. In **MongoDB Atlas** → your cluster → **Browse Collections** (Data Explorer) → database `deep_research` → collection
   `users` → find your user → **Edit** (pencil icon) → change `role` from `"USER"` to `"ADMIN"` → **Update**.
3. In the app, sign out and back in. **Admin** now appears in the sidebar.

## 7. Add your AI model and search key

You can start with free tiers (check the providers' current terms):

- **AI**: a Google **Gemini API** key from Google AI Studio. Gemini's Flash and Flash-Lite models have a free tier with
  rate limits. On the free tier, Google may use what you send to improve its products, so don't research confidential
  material that way.
- **Search**: **Tavily** or **Firecrawl**. Each currently offers 1,000 free credits a month without a credit card.

Then in the app, **Admin → AI providers**:

1. **Credentials → Google Gemini**: paste the key → **Save** (stored encrypted in MongoDB).
2. **List available models** → click a Flash model to copy its ID → **Models → Default model**: provider *Google
   Gemini*, paste the ID → **Save model configuration**.
3. **Connection tests** → **Test connection** sends a tiny real request.
4. **Search providers**: paste your Tavily or Firecrawl key → **Save**.

Then **New research**. If something is missing, the app tells you exactly what before starting a job. On free AI
tiers, start with **Quick** or **Standard** research: Deep mode makes many more model calls and can hit free rate
limits, which the app then retries automatically after the wait the provider asks for.

## Updating

Push to `main`. Render rebuilds only what changed: the API for backend changes, the website for frontend changes.
Research in progress survives a deploy: it checkpoints, and the new instance resumes it.

## Upgrading to the standard layout

When you want research to keep running with no page open, and several jobs in parallel: create a **new** Blueprint
with the path `render.standard.yaml` (separate always-on worker; about $14/month), pointing at the **same** Atlas
database, so your accounts and reports carry over. Once it works, delete the free services. The standard layout can
also send email (paid services can reach SMTP); see the comments in that file.

## Optional

**Custom domain**: add it to the web service (**Settings → Custom Domains**), then update `FRONTEND_URL` on the API to
the new `https://` address.

**Google sign-in** (works on free): create an OAuth client (Google Cloud Console → *APIs & Services → Credentials → OAuth
client ID → Web application*) with the redirect URI `https://YOUR-SITE.onrender.com/api/v1/auth/google/callback`. On
`deep-research-api` set `GOOGLE_AUTH_ENABLED=1`, `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (also change
`GOOGLE_AUTH_ENABLED` to `"1"` in `render.yaml`, or the next Blueprint sync resets it).

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| API logs `Invalid configuration: …` | Read the listed items; usually `MONGODB_URI` or `FRONTEND_URL` (must be `https://`). |
| `ServerSelectionTimeoutError` / Mongo timeouts | Atlas **Network Access** doesn't include `0.0.0.0/0`, or the password in the URI is wrong or not URL-encoded. |
| Sign-in fails with *csrf_failed* | `FRONTEND_URL` doesn't exactly match the website's URL (step 5). |
| *"The research service is unreachable"* | The API is asleep and still waking (wait a minute and retry), crashed (check its logs), or `API_INTERNAL_URL` is wrong (step 5). |
| Every page action fails with *"Direct API access is not allowed"* | The website's `INTERNAL_PROXY_TOKEN` differs from the API's. Copy the API's value (Environment tab) into the web service. |
| *"No AI model is configured yet"* / *"No web search provider is configured"* | Finish step 7. |
| Research activity shows a rate-limit error and *Retrying automatically* | You hit the free tier's per-minute limit; it continues automatically. Use Quick or Standard mode, or a paid key. |
| Services *suspended* until next month | The 750 free hours ran out; don't use uptime pingers. |
| Web build fails with out-of-memory | Retry the deploy; if it persists, temporarily switch the web service to a paid plan for the build. |
