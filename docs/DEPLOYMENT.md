# Phase 8 — Going Public, Step by Step

Read this like a recipe. Do the steps in order. Every step says what to type
and what you should see.

## The plan in one picture

```
   Your laptop            GitHub              Vercel            Render
   ───────────            ──────              ──────            ──────
   the efpvl folder  →   your code   →   the WEBSITE    ←→   the PYTHON
                          online          (what people        ENGINE
                                           see)               (does the maths)
```

Two hosts, because they do different jobs. Vercel serves web pages
brilliantly but cannot run your Python engine (numpy + scipy + matplotlib +
reportlab is far too heavy for it). Render runs Python happily. Both have
free tiers.

You will end up with **one link to share** — your Vercel address. Nobody but
you ever sees the Render one.

---

# PART 1 — Put your code on GitHub

GitHub is a website where code lives. Vercel and Render both read from it,
and it also becomes part of your portfolio.

### 1.1 Install Git (skip if `git --version` already works)

```powershell
winget install -e --id Git.Git
```

**Close PowerShell and open a new one.** Then check:

```powershell
git --version
```
✅ You should see something like `git version 2.4x.x`.

### 1.2 Tell Git who you are (once, ever)

```powershell
git config --global user.name "Sambhav"
git config --global user.email "your-email@example.com"
```

### 1.3 Make a GitHub account

Go to <https://github.com> → **Sign up**. Remember your username.

### 1.4 Turn your folder into a Git repository

```powershell
cd C:\Users\Sambhav\Documents\Explainable_Financial_Product_Valuation_Laboratory\efpvl
git init
git add -A
git status
```

⚠️ **Check the `git status` list before continuing.** You should see your
`engine`, `api`, `frontend`, `docs` files. You should **NOT** see `.venv`,
`node_modules`, or `dist` — those are excluded on purpose. If you do see
them, stop and tell me.

Now save your first snapshot:

```powershell
git commit -m "EFPVL: explainable valuation laboratory, phases 0-7"
```
✅ You should see a long list ending with a summary like `120 files changed`.

### 1.5 Create the repository on GitHub

On <https://github.com>, click **+** (top right) → **New repository**.

- **Repository name:** `efpvl`
- **Description:** `Explainable Financial Product Valuation Laboratory`
- **Public** ✅ (recruiters need to see it)
- **Do NOT** tick "Add a README", ".gitignore", or "license" — you have them
- Click **Create repository**

### 1.6 Push your code up

GitHub now shows you commands. Use these (replace `YOUR-USERNAME`):

```powershell
git remote add origin https://github.com/YOUR-USERNAME/efpvl.git
git branch -M main
git push -u origin main
```

A browser window may pop up asking you to sign in to GitHub — do that.

✅ Refresh your GitHub page. Your code is there, and your README is
displayed underneath. **This alone is already a portfolio asset.**

---

# PART 2 — Deploy the Python engine on Render

### 2.1 Sign up

Go to <https://render.com> → **Get Started** → **Sign in with GitHub** →
authorise it.

### 2.2 Create the service

1. Click **New +** (top right) → **Web Service**
2. Find and select your **efpvl** repository → **Connect**
3. Fill in the form **exactly** like this:

| Field | Value |
|---|---|
| **Name** | `efpvl-api` |
| **Region** | pick the one nearest you (e.g. Singapore) |
| **Branch** | `main` |
| **Root Directory** | *leave empty* |
| **Runtime / Language** | `Python 3` |
| **Build Command** | `pip install -e ./engine && pip install -r api/requirements.txt` |
| **Start Command** | `cd api && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Instance Type** | `Free` |

4. Click **Advanced** and add these **Environment Variables**:

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.7` |
| `EFPVL_RATE_BUDGET` | `120` |
| `EFPVL_CORS_ORIGINS` | `http://localhost:5173` *(temporary — we fix it in Part 4)* |

5. Click **Create Web Service**

### 2.3 Wait and verify

Watch the log. It takes 3–6 minutes (scipy is big). You want to see
`Application startup complete` and a green **Live** badge.

At the top you'll see your address, like
`https://efpvl-api.onrender.com`.

**📌 WRITE THIS ADDRESS DOWN — you need it twice below.**

Test it: open `https://efpvl-api.onrender.com/api/health` in your browser.

✅ You should see:
```json
{"status":"ok","engine_version":"0.3.0","registered_products":11,"registered_models":10}
```

Also try `https://efpvl-api.onrender.com/docs` — your Swagger playground,
now on the internet.

> **About the free tier:** the engine falls asleep after ~15 minutes of no
> visitors and takes up to a minute to wake up. Your app handles this
> gracefully (it says "the free-tier engine may be waking up" and retries).
> If you'd rather it never sleeps, Render's cheapest paid tier is a few
> dollars a month.

---

# PART 3 — Deploy the website on Vercel

### 3.1 Sign up

<https://vercel.com> → **Sign Up** → **Continue with GitHub** → authorise.

### 3.2 Import the project

1. Click **Add New…** → **Project**
2. Find **efpvl** → **Import**
3. Now the important bit — set these:

| Field | Value |
|---|---|
| **Framework Preset** | `Vite` |
| **Root Directory** | click **Edit** → choose **`frontend`** ⚠️ |
| **Build Command** | `npm run build` (default is fine) |
| **Output Directory** | `dist` (default is fine) |

⚠️ **Root Directory = `frontend` is the step people get wrong.** Your
website lives in that subfolder, not at the top.

4. Expand **Environment Variables** and add one:

| Key | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://efpvl-api.onrender.com/api` |

Use **your** Render address from step 2.3, and note it **ends with `/api`**
and has **no trailing slash**.

5. Click **Deploy** and wait ~1 minute.

✅ You'll get confetti and an address like `https://efpvl.vercel.app`.

**📌 WRITE THIS ADDRESS DOWN TOO.**

---

# PART 4 — Introduce them to each other

Right now your website loads, but the engine refuses its calls — the engine
was told to trust only `localhost`. Let's fix that.

1. Go back to **Render** → your `efpvl-api` service → **Environment** (left
   sidebar)
2. Edit **`EFPVL_CORS_ORIGINS`** and set it to your Vercel address:

   ```
   https://efpvl.vercel.app
   ```

   ⚠️ Exactly: `https://`, no trailing slash, no `/api`.

3. Click **Save Changes**. Render restarts automatically (~1 minute).

---

# PART 5 — Test your live laboratory 🎉

Open your Vercel link on your laptop:

- [ ] The status bar top-right shows a **green dot** and `11 PRODUCTS · 10 MODELS`
      *(first load may take up to a minute while the engine wakes — that's
      the free tier, and the app says so)*
- [ ] **Valuation** → European Option → Calculate → the trace rail appears
- [ ] **Sensitivity** → drag a slider → the Greeks move
- [ ] **Vol Smile** → drag the strike → the mispricing figure changes
- [ ] **Comparison** → run several models
- [ ] **Export** → download a PDF → open it
- [ ] Paste a deep link directly, e.g. `https://efpvl.vercel.app/smile`

Then open the same link **on your phone**.

If the status dot is red, jump to Troubleshooting below.

---

# PART 6 — Put it on your portfolio

**Simplest:** add a link/button on your portfolio pointing at your Vercel
address, plus a line describing it.

**Nicer — your own subdomain** (e.g. `lab.yourdomain.com`):

1. Vercel → your project → **Settings** → **Domains** → **Add**
2. Type `lab.yourdomain.com` → Vercel shows you a DNS record (a `CNAME`)
3. Add that record at your domain registrar
4. Wait for it to go green (minutes to an hour)
5. ⚠️ **Then go back to Render and add the new address to
   `EFPVL_CORS_ORIGINS`**, comma-separated:
   ```
   https://efpvl.vercel.app,https://lab.yourdomain.com
   ```

Also add your live link and GitHub repo to the top of your CV/LinkedIn.

---

# From now on: updating your live site

Every time you change code:

```powershell
git add -A
git commit -m "describe what you changed"
git push
```

That's it. Vercel and Render both watch GitHub and redeploy themselves
automatically, running your tests in CI along the way.

---

# Troubleshooting

**🔴 Status dot red / "Cannot reach the valuation engine"**
1. Open `https://YOUR-RENDER-URL/api/health` directly. Nothing? The engine
   is asleep or crashed — check Render → **Logs**.
2. Health works but the site still fails → it's CORS. Check
   `EFPVL_CORS_ORIGINS` on Render matches your Vercel address **exactly**
   (`https://`, no trailing slash).
3. Also check Vercel's `VITE_API_BASE_URL` **ends in `/api`**. Changing it
   requires a **redeploy** (Vercel → Deployments → ⋯ → Redeploy) because it
   is baked in at build time.

**🟡 First visit is slow (~40–60 seconds)**
Normal on Render's free tier: the machine was asleep. Subsequent requests
are fast. Options: accept it, mention it in your portfolio blurb, ping
`/api/health` with a free uptime monitor (e.g. UptimeRobot) every 10
minutes, or upgrade Render.

**❌ Vercel build fails**
Almost always Root Directory. Vercel → Settings → General → **Root
Directory** must be `frontend`.

**❌ Render build fails**
Read the log's last 20 lines. Common causes: `PYTHON_VERSION` not set to
`3.12.7`, or a typo in the Build Command (it must include both `pip install`
parts joined by `&&`).

**❌ "Too many requests" (429)**
Your own rate limiter doing its job (120 requests/IP/minute). Wait a minute.
Raise `EFPVL_RATE_BUDGET` on Render if you truly need more.

**🔀 Pushed changes but the site looks the same**
Check the Vercel/Render dashboards for a running deployment, and hard-refresh
your browser (Ctrl+Shift+R).
